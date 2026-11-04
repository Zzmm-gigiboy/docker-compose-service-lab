package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
)

func TestLinksCRUD(t *testing.T) {
	path := filepath.Join(t.TempDir(), "links.json")
	h := newStore(path).handler()
	request := func(method, p string, body []byte) *httptest.ResponseRecorder {
		r := httptest.NewRequest(method, p, bytes.NewReader(body))
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		return w
	}
	if got := request("GET", "/health", nil).Code; got != 200 {
		t.Fatalf("health: %d", got)
	}
	if got := request("POST", "/api/links", []byte(`{"title":"Bad","url":"javascript:alert(1)"}`)).Code; got != 422 {
		t.Fatalf("should reject URL: %d", got)
	}
	created := request("POST", "/api/links", []byte(`{"title":"Go Docs","url":"https://go.dev/doc/","tags":["language"]}`))
	if created.Code != 201 {
		t.Fatalf("create: %d %s", created.Code, created.Body)
	}
	var l Link
	if err := json.Unmarshal(created.Body.Bytes(), &l); err != nil || l.ID != 1 {
		t.Fatalf("invalid response: %v", err)
	}
	listed := request("GET", "/api/links?q=language", nil)
	var items []Link
	if err := json.Unmarshal(listed.Body.Bytes(), &items); err != nil || len(items) != 1 {
		t.Fatalf("search failed: %s", listed.Body)
	}
	if len(newStore(path).links) != 1 {
		t.Fatal("JSON storage did not persist")
	}
	if got := request("DELETE", "/api/links/1", nil).Code; got != 204 {
		t.Fatalf("delete: %d", got)
	}
	if got := request("DELETE", "/api/links/1", nil).Code; got != 404 {
		t.Fatalf("404 expected: %d", got)
	}
}

func TestLinksValidation(t *testing.T) {
	h := newStore("").handler()
	post := func(body string) int {
		r := httptest.NewRequest("POST", "/api/links", strings.NewReader(body))
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		return w.Code
	}

	tests := []struct {
		name       string
		body       string
		wantStatus int
	}{
		{
			name:       "ftp scheme rejected",
			body:       `{"title":"FTP Site","url":"ftp://ftp.example.com/file"}`,
			wantStatus: 422,
		},
		{
			name:       "missing scheme rejected",
			body:       `{"title":"No Scheme","url":"example.com/page"}`,
			wantStatus: 422,
		},
		{
			name:       "empty title rejected",
			body:       `{"title":"","url":"https://example.com"}`,
			wantStatus: 422,
		},
		{
			name:       "whitespace only title rejected",
			body:       `{"title":"   ","url":"https://example.com"}`,
			wantStatus: 422,
		},
		{
			name:       "title exceeding 120 chars rejected",
			body:       fmt.Sprintf(`{"title":"%s","url":"https://example.com"}`, strings.Repeat("A", 121)),
			wantStatus: 422,
		},
		{
			name:       "tags exceeding 10 items rejected",
			body:       `{"title":"Too Many Tags","url":"https://example.com","tags":["1","2","3","4","5","6","7","8","9","10","11"]}`,
			wantStatus: 422,
		},
		{
			name:       "valid 120 char title accepted",
			body:       fmt.Sprintf(`{"title":"%s","url":"https://example.com"}`, strings.Repeat("A", 120)),
			wantStatus: 201,
		},
		{
			name:       "valid http url accepted",
			body:       `{"title":"HTTP Link","url":"http://example.com/test"}`,
			wantStatus: 201,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := post(tc.body); got != tc.wantStatus {
				t.Errorf("%s: got status %d, want %d", tc.name, got, tc.wantStatus)
			}
		})
	}
}

func TestLinksMalformedJSON(t *testing.T) {
	h := newStore("").handler()
	r := httptest.NewRequest("POST", "/api/links", strings.NewReader(`{invalid-json`))
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != 400 {
		t.Errorf("expected 400 for malformed json, got %d", w.Code)
	}
}

func TestLinksSearchAndSort(t *testing.T) {
	h := newStore("").handler()
	links := []string{
		`{"title":"Zebra Documentation","url":"https://zebra.org","tags":["animals"]}`,
		`{"title":"Apple Developer","url":"https://developer.apple.com","tags":["mobile","ios"]}`,
		`{"title":"Banana Guide","url":"https://banana.dev","tags":["fruit"]}`,
	}
	for _, l := range links {
		r := httptest.NewRequest("POST", "/api/links", strings.NewReader(l))
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != 201 {
			t.Fatalf("failed to insert link: %d", w.Code)
		}
	}

	// GET all links sorted alphabetically by title
	r := httptest.NewRequest("GET", "/api/links", nil)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	var all []Link
	if err := json.Unmarshal(w.Body.Bytes(), &all); err != nil {
		t.Fatalf("failed to unmarshal links: %v", err)
	}
	if len(all) != 3 {
		t.Fatalf("expected 3 links, got %d", len(all))
	}
	if all[0].Title != "Apple Developer" || all[1].Title != "Banana Guide" || all[2].Title != "Zebra Documentation" {
		t.Errorf("unexpected sort order: %v, %v, %v", all[0].Title, all[1].Title, all[2].Title)
	}

	// Filter by tag
	rTag := httptest.NewRequest("GET", "/api/links?q=mobile", nil)
	wTag := httptest.NewRecorder()
	h.ServeHTTP(wTag, rTag)
	var tagResults []Link
	if err := json.Unmarshal(wTag.Body.Bytes(), &tagResults); err != nil || len(tagResults) != 1 {
		t.Fatalf("tag query failed: %s", wTag.Body)
	}
	if tagResults[0].Title != "Apple Developer" {
		t.Errorf("expected Apple Developer, got %s", tagResults[0].Title)
	}

	// Filter with no matches
	rNone := httptest.NewRequest("GET", "/api/links?q=nonexistent_query", nil)
	wNone := httptest.NewRecorder()
	h.ServeHTTP(wNone, rNone)
	var noneResults []Link
	if err := json.Unmarshal(wNone.Body.Bytes(), &noneResults); err != nil || len(noneResults) != 0 {
		t.Fatalf("expected 0 results, got %d", len(noneResults))
	}
}

func TestDeleteValidation(t *testing.T) {
	h := newStore("").handler()

	// Non-numeric ID returns 400
	rBadID := httptest.NewRequest("DELETE", "/api/links/not-an-id", nil)
	wBadID := httptest.NewRecorder()
	h.ServeHTTP(wBadID, rBadID)
	if wBadID.Code != 400 {
		t.Errorf("expected 400 for non-numeric id, got %d", wBadID.Code)
	}

	// Non-existent ID returns 404
	rNotFound := httptest.NewRequest("DELETE", "/api/links/999", nil)
	wNotFound := httptest.NewRecorder()
	h.ServeHTTP(wNotFound, rNotFound)
	if wNotFound.Code != 404 {
		t.Errorf("expected 404 for missing id, got %d", wNotFound.Code)
	}
}

func TestStorePersistenceAndRecovery(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "links.json")

	store1 := newStore(path)
	h1 := store1.handler()

	// Add link
	r := httptest.NewRequest("POST", "/api/links", strings.NewReader(`{"title":"Persistent Link","url":"https://example.com"}`))
	w := httptest.NewRecorder()
	h1.ServeHTTP(w, r)
	if w.Code != 201 {
		t.Fatalf("create failed: %d", w.Code)
	}

	// Reload store from the same file
	store2 := newStore(path)
	if len(store2.links) != 1 {
		t.Fatalf("expected 1 link recovered from disk, got %d", len(store2.links))
	}
	if store2.links[0].Title != "Persistent Link" {
		t.Errorf("expected 'Persistent Link', got %s", store2.links[0].Title)
	}
	if store2.next != 2 {
		t.Errorf("expected next ID to be 2, got %d", store2.next)
	}
}
