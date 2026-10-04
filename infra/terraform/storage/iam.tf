# Minimum permissions for the gateway (archive JSON, presigned reads, retention deletes)
# and LiveKit Egress (recording upload), scoped to this bucket and the archive prefix.
data "aws_iam_policy_document" "archive_access" {
  statement {
    sid       = "ListArchivePrefix"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.archive.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${local.prefix}/*"]
    }
  }

  statement {
    sid       = "BucketLocation"
    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.archive.arn]
  }

  statement {
    sid = "ArchiveObjects"
    actions = [
      "s3:PutObject",
      "s3:PutObjectTagging",
      "s3:GetObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.archive.arn}/${local.prefix}/*"]
  }
}

resource "aws_iam_policy" "archive_access" {
  name        = "${var.project_name}-${var.environment}-meeting-archive"
  description = "MeetQ ${var.environment}: read/write/delete meeting archives under s3://${local.bucket_name}/${local.prefix}/"
  policy      = data.aws_iam_policy_document.archive_access.json
}

resource "aws_iam_user" "archive" {
  count = var.create_iam_user ? 1 : 0

  name = "${var.project_name}-${var.environment}-meeting-archive"
  path = "/meetq/"
}

resource "aws_iam_user_policy_attachment" "archive" {
  count = var.create_iam_user ? 1 : 0

  user       = aws_iam_user.archive[0].name
  policy_arn = aws_iam_policy.archive_access.arn
}

resource "aws_iam_role_policy_attachment" "archive" {
  for_each = toset(var.attach_to_role_names)

  role       = each.value
  policy_arn = aws_iam_policy.archive_access.arn
}
