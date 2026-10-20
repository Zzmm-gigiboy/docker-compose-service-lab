FROM golang:1.23-alpine AS build
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 go build -o /app .
FROM alpine:3.20
WORKDIR /data
COPY --from=build /app /usr/local/bin/link-api
ENV PORT=8080 LINK_STORE_FILE=/data/links.json
EXPOSE 8080
CMD ["link-api"]
