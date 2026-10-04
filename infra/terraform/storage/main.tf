data "aws_caller_identity" "current" {}

locals {
  bucket_name = var.bucket_name != "" ? var.bucket_name : "${var.project_name}-${var.environment}-meeting-archive-${data.aws_caller_identity.current.account_id}"
  prefix      = trim(var.archive_prefix, "/")
}

# Private bucket for meeting recordings (MP4 from LiveKit Egress) and archived meeting JSON.
resource "aws_s3_bucket" "archive" {
  bucket        = local.bucket_name
  force_destroy = var.force_destroy
}

# ACLs disabled: the bucket owner owns every object, public ACLs are impossible.
resource "aws_s3_bucket_ownership_controls" "archive" {
  bucket = aws_s3_bucket.archive.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "archive" {
  bucket = aws_s3_bucket.archive.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

# SSE-S3 for every object, including uploads that don't send an encryption header.
resource "aws_s3_bucket_server_side_encryption_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Versioning is intentionally NOT enabled: retention deletes must remove the bytes,
# and a delete marker over older versions would keep expired meeting content around.

data "aws_iam_policy_document" "bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.archive.arn,
      "${aws_s3_bucket.archive.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "archive" {
  bucket = aws_s3_bucket.archive.id
  policy = data.aws_iam_policy_document.bucket.json

  # A deny-only policy is not "public", but apply it after the public access block.
  depends_on = [aws_s3_bucket_public_access_block.archive]
}

# Safety net only. Per-meeting retention is enforced by the application
# (meeting_archives.expires_at + cleanup worker), because admins can set a
# different retention for every meeting; a bucket-wide expiry would be wrong.
resource "aws_s3_bucket_lifecycle_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = var.abort_incomplete_multipart_days
    }
  }
}
