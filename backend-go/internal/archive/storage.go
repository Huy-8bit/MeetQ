package archive

import (
	"context"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"

	"meetq/backend-go/internal/config"
)

type Storage struct {
	client        *s3.Client
	presignClient *s3.PresignClient
	bucket        string
	cfg           *config.Config
}

func NewStorage(ctx context.Context, cfg *config.Config) (*Storage, error) {
	if cfg.MeetingArchiveBucket == "" {
		return nil, nil
	}

	opts := []func(*awsconfig.LoadOptions) error{}
	if cfg.AWSRegion != "" {
		opts = append(opts, awsconfig.WithRegion(cfg.AWSRegion))
	} else {
		opts = append(opts, awsconfig.WithRegion("us-east-1"))
	}

	// Custom endpoint for local MinIO / RustFS
	if cfg.S3EndpointURL != "" {
		opts = append(opts, awsconfig.WithBaseEndpoint(cfg.S3EndpointURL))
	}

	awsCfg, err := awsconfig.LoadDefaultConfig(ctx, opts...)
	if err != nil {
		return nil, fmt.Errorf("aws config error: %w", err)
	}

	s3Client := s3.NewFromConfig(awsCfg, func(o *s3.Options) {
		o.UsePathStyle = cfg.S3ForcePathStyle
	})

	// Public endpoint for browser presigning if specified
	var presignClient *s3.PresignClient
	if cfg.S3PublicEndpointURL != "" && cfg.S3PublicEndpointURL != cfg.S3EndpointURL {
		pubOpts := append(opts, awsconfig.WithBaseEndpoint(cfg.S3PublicEndpointURL))
		pubAwsCfg, err := awsconfig.LoadDefaultConfig(ctx, pubOpts...)
		if err == nil {
			pubClient := s3.NewFromConfig(pubAwsCfg, func(o *s3.Options) {
				o.UsePathStyle = cfg.S3ForcePathStyle
			})
			presignClient = s3.NewPresignClient(pubClient)
		}
	}
	if presignClient == nil {
		presignClient = s3.NewPresignClient(s3Client)
	}

	return &Storage{
		client:        s3Client,
		presignClient: presignClient,
		bucket:        cfg.MeetingArchiveBucket,
		cfg:           cfg,
	}, nil
}

func (s *Storage) PresignedGetURL(ctx context.Context, key string, expiresIn time.Duration, downloadName *string) (string, error) {
	if s == nil || s.presignClient == nil {
		return "", fmt.Errorf("storage unavailable")
	}

	input := &s3.GetObjectInput{
		Bucket: aws.String(s.bucket),
		Key:    aws.String(key),
	}
	if downloadName != nil && *downloadName != "" {
		input.ResponseContentDisposition = aws.String(fmt.Sprintf(`attachment; filename="%s"`, *downloadName))
	}

	req, err := s.presignClient.PresignGetObject(ctx, input, s3.WithPresignExpires(expiresIn))
	if err != nil {
		return "", err
	}
	return req.URL, nil
}

func (s *Storage) DeletePrefix(ctx context.Context, prefix string) (int, error) {
	if s == nil || s.client == nil {
		return 0, nil
	}
	if !strings.HasSuffix(prefix, "/") {
		return 0, fmt.Errorf("prefix must end with '/'")
	}

	var deletedCount int
	var continuationToken *string
	for {
		listRes, err := s.client.ListObjectsV2(ctx, &s3.ListObjectsV2Input{
			Bucket:            aws.String(s.bucket),
			Prefix:            aws.String(prefix),
			ContinuationToken: continuationToken,
		})
		if err != nil {
			return deletedCount, err
		}
		if len(listRes.Contents) == 0 {
			break
		}

		for _, item := range listRes.Contents {
			_, err := s.client.DeleteObject(ctx, &s3.DeleteObjectInput{
				Bucket: aws.String(s.bucket),
				Key:    item.Key,
			})
			if err != nil {
				return deletedCount, err
			}
			deletedCount++
		}

		if !aws.ToBool(listRes.IsTruncated) {
			break
		}
		continuationToken = listRes.NextContinuationToken
	}

	return deletedCount, nil
}

// Dummy credentials import helper to make sure unused import isn't an issue
var _ = credentials.NewStaticCredentialsProvider
var _ = url.QueryEscape
