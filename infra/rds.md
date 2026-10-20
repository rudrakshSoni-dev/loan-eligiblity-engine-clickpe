# RDS PostgreSQL (T11)

Created with the AWS CLI on 2026-10-21 in `ap-southeast-2`, default VPC `vpc-0cddb8b4387b5bbdc`.

## Resulting instance

| Setting | Value | Why |
|---|---|---|
| Identifier | `clickpe-db` | |
| Class | `db.t4g.micro` | Smallest Graviton class; free-tier eligible |
| Engine | PostgreSQL 16.9, minor auto-upgrade off | Pinned so the demo does not change under us |
| Storage | 20 GB gp3, encrypted | Free-tier size; no provisioned IOPS |
| Availability | Single-AZ | Demo scale; Multi-AZ doubles cost (production upgrade) |
| Publicly accessible | **No** | Only reachable from inside the VPC |
| Security group | `clickpe-rds-sg` (`sg-0f0ca5e2b7cb5e1c3`), no inbound rules yet | 5432 is opened to the Lambda SG (after `sls deploy`) and the n8n EC2 SG (T12) only, by SG reference, never by CIDR |
| Subnet group | `clickpe-db-subnets` (2a, 2b, 2c) | |
| Backups | 1 day | |
| Deletion protection | On | |
| Parameter group | `default.postgres16` | `rds.force_ssl` already defaults to 1 on PG 15+ |
| Endpoint | stored in SSM `/clickpe/db/host` | Resolved into Lambda env at deploy |

## Commands

```bash
export AWS_PROFILE=clickpe AWS_REGION=ap-southeast-2 AWS_PAGER=""

SG=$(aws ec2 create-security-group --group-name clickpe-rds-sg \
  --description "RDS Postgres; 5432 from Lambda SG and n8n SG only" \
  --vpc-id vpc-0cddb8b4387b5bbdc --query GroupId --output text)

aws rds create-db-subnet-group --db-subnet-group-name clickpe-db-subnets \
  --db-subnet-group-description "default VPC subnets" \
  --subnet-ids subnet-04a43c129719297db subnet-049a812f86eb26015 subnet-09695ef5d76d947ed

aws rds create-db-instance --db-instance-identifier clickpe-db \
  --engine postgres --engine-version 16.9 --db-instance-class db.t4g.micro \
  --allocated-storage 20 --storage-type gp3 --no-multi-az --no-publicly-accessible \
  --db-subnet-group-name clickpe-db-subnets --vpc-security-group-ids "$SG" \
  --master-username clickpe --db-name clickpe \
  --master-user-password "$(aws ssm get-parameter --name /clickpe/db/password --with-decryption --query Parameter.Value --output text)" \
  --backup-retention-period 1 --deletion-protection --storage-encrypted \
  --no-enable-performance-insights --no-auto-minor-version-upgrade

aws rds wait db-instance-available --db-instance-identifier clickpe-db

aws ssm put-parameter --name /clickpe/db/host --overwrite --type String \
  --value "$(aws rds describe-db-instances --db-instance-identifier clickpe-db --query 'DBInstances[0].Endpoint.Address' --output text)"
```

The master password never appears on screen or in a file: it is read from the existing SecureString `/clickpe/db/password`.

Set `AWS_PAGER=""` first. With the pager on, the JSON output of `create-db-subnet-group` opens `less` and the rest of a pasted block does not run as expected.

## Privacy proof

From a laptop outside AWS:

```
$ getent hosts clickpe-db.c7mkqekmcsrq.ap-southeast-2.rds.amazonaws.com
172.31.32.255   clickpe-db.c7mkqekmcsrq.ap-southeast-2.rds.amazonaws.com
$ timeout 8 bash -c "</dev/tcp/clickpe-db.c7mkqekmcsrq.ap-southeast-2.rds.amazonaws.com/5432"
bash: connect: No route to host
```

Public DNS returns only a private VPC address, so there is no path from the internet at all, before the security group is even consulted.

## Checks run from inside the VPC (T12)

`SHOW rds.force_ssl`, a rejected `sslmode=disable` connection, and `SHOW max_connections` need a client inside the VPC. They are run from the n8n EC2 instance in T12 and recorded in `PROGRESS.md` under T11.
