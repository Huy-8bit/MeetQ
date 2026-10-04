output "bucket_name" {
  description = "MEETING_ARCHIVE_BUCKET for the gateway and the egress `s3.bucket` setting."
  value       = aws_s3_bucket.archive.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.archive.arn
}

output "aws_region" {
  description = "AWS_REGION for the gateway and the egress `s3.region` setting."
  value       = var.aws_region
}

output "archive_prefix" {
  value = local.prefix
}

output "iam_policy_arn" {
  value = aws_iam_policy.archive_access.arn
}

output "iam_user_name" {
  description = "Create its access key out of band: aws iam create-access-key --user-name <this>."
  value       = var.create_iam_user ? aws_iam_user.archive[0].name : null
}
