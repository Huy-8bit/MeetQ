# Terraform: meeting archive storage (AWS S3)

Private bucket for meeting recordings (MP4 written by LiveKit Egress) and archived
meeting JSON, plus least-privilege IAM. See [docs/meeting-recording-and-retention.md](../../../docs/meeting-recording-and-retention.md).

| Resource | Purpose |
| --- | --- |
| `aws_s3_bucket.archive` | `<project>-<env>-meeting-archive-<account>` |
| `aws_s3_bucket_ownership_controls` | `BucketOwnerEnforced`: ACLs disabled |
| `aws_s3_bucket_public_access_block` | All four public-access blocks on |
| `aws_s3_bucket_server_side_encryption_configuration` | SSE-S3 (AES256) default encryption |
| `aws_s3_bucket_policy` | Deny any request without TLS (`aws:SecureTransport = false`) |
| `aws_s3_bucket_lifecycle_configuration` | Safety net only: abort incomplete multipart uploads after 1 day. Retention is enforced by the application per meeting |
| `aws_iam_policy.archive_access` | List/Get/Put/Tag/Delete/AbortMultipart only under `meetings/*` of this bucket |
| `aws_iam_user.archive` (+ attachment) | For a backend outside AWS. **No access key in Terraform**; create it with `aws iam create-access-key` |
| `aws_iam_role_policy_attachment` | Optional: attach the policy to existing roles (`attach_to_role_names`) |

Versioning is deliberately not enabled, so retention deletes remove the bytes.

```bash
cp env/prod.tfvars.example env/prod.tfvars
terraform init
terraform workspace select -or-create prod
terraform plan  -var-file=env/prod.tfvars
terraform apply -var-file=env/prod.tfvars
```

Provider `hashicorp/aws ~> 6.67`; `.terraform.lock.hcl` is committed. Credentials come from the standard AWS chain (`AWS_PROFILE`, SSO, env, instance role). State is local per workspace (git-ignored).
