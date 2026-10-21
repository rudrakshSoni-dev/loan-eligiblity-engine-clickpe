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

## Launch commands

The instance was first created interactively. These commands were rebuilt on 2026-10-22 from the live instance's settings (`describe-instances`, `describe-volumes`, `get-role`) and were not re-run, so read them as the recipe for the settings in the table above, not as a tested script. Replace the subnet, VPC and AMI lookups if you use another account.

```bash
export AWS_PROFILE=clickpe AWS_REGION=ap-southeast-2 AWS_PAGER=""
VPC=vpc-0cddb8b4387b5bbdc
SUBNET=subnet-04a43c129719297db

aws iam create-role --role-name clickpe-n8n-ec2-role \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name clickpe-n8n-ec2-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam create-instance-profile --instance-profile-name clickpe-n8n-ec2-profile
aws iam add-role-to-instance-profile --instance-profile-name clickpe-n8n-ec2-profile \
  --role-name clickpe-n8n-ec2-role

N8N_SG=$(aws ec2 create-security-group --group-name clickpe-n8n-sg \
  --description "n8n; no inbound from the internet" --vpc-id "$VPC" --query GroupId --output text)

AMI=$(aws ssm get-parameter \
  --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 \
  --query Parameter.Value --output text)

aws ec2 run-instances --image-id "$AMI" --instance-type t4g.small --subnet-id "$SUBNET" \
  --security-group-ids "$N8N_SG" --associate-public-ip-address \
  --iam-instance-profile Name=clickpe-n8n-ec2-profile \
  --metadata-options HttpTokens=required,HttpPutResponseHopLimit=2,HttpEndpoint=enabled \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=20,VolumeType=gp3,Encrypted=true}' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=clickpe-n8n}]'
```

The IAM role must also be allowed to assume the SES-only role; the policy documents and the order are in `infra/iam/` and the "Credentials (T24)" section of `infra/n8n.md`.

After `RDS_SG` (`clickpe-rds-sg`) exists and the stack is deployed, open the database and the webhook port to the right groups by reference. `LAMBDA_SG` is the stack's `LambdaSecurityGroup`:

```bash
aws ec2 authorize-security-group-ingress --group-id "$RDS_SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=5432,ToPort=5432,UserIdGroupPairs=[{GroupId=$N8N_SG}]"
aws ec2 authorize-security-group-ingress --group-id "$RDS_SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=5432,ToPort=5432,UserIdGroupPairs=[{GroupId=$LAMBDA_SG}]"
aws ec2 authorize-security-group-ingress --group-id "$N8N_SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=5678,ToPort=5678,UserIdGroupPairs=[{GroupId=$LAMBDA_SG}]"
```

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
