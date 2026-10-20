# EC2 for n8n (T12)

Created with the AWS CLI on 2026-10-21 in `ap-southeast-2`, default VPC `vpc-0cddb8b4387b5bbdc`.

| Setting | Value | Why |
|---|---|---|
| Instance | `i-02ffa9d08e8403a4a`, `t4g.small`, AL2023 arm64 | Largest class the cost rules allow; Graviton |
| Subnet | `subnet-04a43c129719297db` (public), public IP used for outbound only | Reaches Groq, crawl targets, SES and SSM through the free Internet Gateway; no NAT |
| Security group | `clickpe-n8n-sg` (`sg-0fd3ef0dd40c9f8e3`), **no inbound rules** | Admin access is SSM only; 5678 from the Lambda SG is added after `sls deploy` |
| Instance role | `clickpe-n8n-ec2-role` with `AmazonSSMManagedInstanceCore` | Session Manager and Run Command; the SES-only role is added in T24 |
| Metadata | IMDSv2 required, hop limit 2 | Containers can reach the instance role (T24) without allowing IMDSv1 |
| Volume | 20 GB gp3, encrypted | |
| Swap | 2 GB file, persisted in `/etc/fstab` | `t4g.small` has 2 GB RAM |
| Software | Docker 25.0.14, Compose v2.29.7, `psql` 16, RDS CA bundle at `/opt/clickpe/global-bundle.pem` | Installed by `infra/ec2/setup.sh` |
| RDS ingress | `clickpe-rds-sg` allows 5432 from `clickpe-n8n-sg` by SG reference | |

## Setup

Run from the repo root. SSM Run Command needs no Session Manager plugin and runs as root:

```bash
export AWS_PROFILE=clickpe AWS_REGION=ap-southeast-2 AWS_PAGER=""
I=i-02ffa9d08e8403a4a
B64=$(base64 -w0 infra/ec2/setup.sh)
CMD=$(aws ssm send-command --instance-ids $I --document-name AWS-RunShellScript \
  --parameters "commands=[\"echo $B64 | base64 -d > /tmp/setup.sh\",\"bash /tmp/setup.sh\"]" \
  --query Command.CommandId --output text)
aws ssm wait command-executed --command-id $CMD --instance-id $I
aws ssm get-command-invocation --command-id $CMD --instance-id $I \
  --query '[Status,StandardOutputContent]' --output text
```

## Checks from inside the VPC (interactive SSM session)

```
verify-full connection:  ssl = t, TLSv1.3, TLS_AES_256_GCM_SHA384
max_connections:         79
sslmode=disable:         FATAL: no pg_hba.conf entry for host "172.31.26.164", user "clickpe", database "clickpe", no encryption
```

`SHOW rds.force_ssl` is not valid SQL on RDS because it is a parameter-group setting. It was read through the RDS API instead:

```
$ aws rds describe-db-parameters --db-parameter-group-name default.postgres16 \
    --query "Parameters[?ParameterName=='rds.force_ssl'].[ParameterName,ParameterValue,Source]" --output text
rds.force_ssl   1   system
```

The n8n SG's `IpPermissions` is `[]`, and the RDS SG's only 5432 source is `sg-0fd3ef0dd40c9f8e3`.
