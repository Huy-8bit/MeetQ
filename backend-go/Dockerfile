# Multi-stage Dockerfile for MeetQ Go Backend
FROM golang:1.26-alpine AS builder

WORKDIR /src

# Cache dependencies
COPY go.mod go.sum ./
RUN go mod download

# Copy source
COPY . .

# Build statically linked binary
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /bin/meetq-backend-go cmd/api/main.go

# Minimal runtime image
FROM alpine:3.20

RUN apk --no-cache add ca-certificates tzdata \
    && addgroup -S appgroup && adduser -S appuser -G appgroup

WORKDIR /app

COPY --from=builder /bin/meetq-backend-go /app/meetq-backend-go

USER appuser

EXPOSE 8080

ENTRYPOINT ["/app/meetq-backend-go"]
