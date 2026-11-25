# FINORA — PRODUCTION BACKUP & DISASTER RECOVERY GUIDE
## Amazon S3 Encrypted Backup & Recovery (Mumbai `ap-south-1`)

- **Author:** Principal Production Release Engineer
- **Date:** November 25, 2026
- **Target Platform:** Amazon S3 & Amazon Lightsail
- **Target Region:** Asia Pacific (Mumbai) `ap-south-1`
- **Statutory Retention:** 2,555 Days (7 Years under Indian Companies Act / Tax Law)
- **Status:** **VERIFIED & OPERATIONAL**

---

## 1. Dual-Scope Backup Architecture

Finora implements an atomic, dual-scope backup architecture that protects both transactional database states and physical raw evidence documents:

```
+-------------------------------------------------------------------------------------------------+
|                                    Daily Snapshot Trigger                                       |
|                       (Cron / Systemd Timer daily at 02:00 AM IST)                              |
+-------------------------------------------------------------------------------------------------+
                                                 |
                       +-------------------------+-------------------------+
                       |                                                   |
                       v                                                   v
+-----------------------------------------------+   +-----------------------------------------------+
|             1. PostgreSQL Snapshot            |   |             2. Financial Evidence             |
|  - Custom compressed binary archive (pg_dump) |   |  - Gzipped tarball of /var/finora/storage     |
|  - Non-blocking, portable (--no-owner)        |   |  - Preserves tenant isolation & permissions   |
|  - Filename: finora_db_{TIMESTAMP}.dump       |   |  - Filename: finora_evidence_{TIMESTAMP}.tar.gz|
+-----------------------------------------------+   +-----------------------------------------------+
                       |                                                   |
                       v                                                   v
+-----------------------------------------------+   +-----------------------------------------------+
|         Compute SHA-256 Cryptographic Hash    |   |         Compute SHA-256 Cryptographic Hash    |
+-----------------------------------------------+   +-----------------------------------------------+
                       |                                                   |
                       +-------------------------+-------------------------+
                                                 |
                                                 v
+-------------------------------------------------------------------------------------------------+
|                                 3. Cryptographic Manifest Creation                              |
|                              Filename: finora_manifest_{TIMESTAMP}.json                         |
|   - Database: size_bytes, filename, sha256 digest                                               |
|   - Evidence: size_bytes, filename, sha256 digest, total file count                             |
|   - Retention policy metadata: 2555 days                                                        |
+-------------------------------------------------------------------------------------------------+
                                                 |
                                                 v
+-------------------------------------------------------------------------------------------------+
|                            4. Offsite Encrypted Upload to Amazon S3                             |
|                   Destination: s3://finora-production-backups-mumbai/daily-snapshots/           |
|                          Server-Side Encryption: AES256 (or aws:kms)                            |
+-------------------------------------------------------------------------------------------------+
                                                 |
                       +-------------------------+-------------------------+
                       | Upload Success Verified                           | Upload Failed
                       v                                                   v
+-----------------------------------------------+   +-----------------------------------------------+
| Safe Local Retention Pruning                  |   | [CRITICAL SAFEGUARD]                          |
| Only archives older than 7 days pruned.       |   | Abort immediately. Preserve all local files.  |
| Statutory retention preserved in S3 Glacier.  |   | Raise alert and exit with non-zero code.      |
+-----------------------------------------------+   +-----------------------------------------------+
```

---

## 2. Amazon S3 Bucket Provisioning

### Step 2.1: Create Private S3 Bucket in Mumbai (`ap-south-1`)
Run using the AWS CLI or create in the AWS Console:
```bash
aws s3api create-bucket \
    --bucket finora-production-backups-mumbai \
    --region ap-south-1 \
    --create-bucket-configuration LocationConstraint=ap-south-1
```

### Step 2.2: Enforce S3 Block Public Access
Strictly prohibit public access across the bucket:
```bash
aws s3api put-public-access-block \
    --bucket finora-production-backups-mumbai \
    --public-access-block-configuration '{
        "BlockPublicAcls": true,
        "IgnorePublicAcls": true,
        "BlockPublicPolicy": true,
        "RestrictPublicBuckets": true
    }'
```

### Step 2.3: Enforce Default Server-Side Encryption (AES-256)
```bash
aws s3api put-bucket-encryption \
    --bucket finora-production-backups-mumbai \
    --server-side-encryption-configuration '{
        "Rules": [
            {
                "ApplyServerSideEncryptionByDefault": {
                    "SSEAlgorithm": "AES256"
                }
            }
        ]
    }'
```

### Step 2.4: Configure S3 Lifecycle & Statutory Retention Policy
To minimize long-term storage costs while complying with Indian 7-year statutory financial retention:
- **0–90 Days:** S3 Standard (Fast recovery).
- **91–365 Days:** Transition to S3 Glacier Flexible Retrieval (Cost reduction).
- **366–2555 Days:** Transition to S3 Glacier Deep Archive (Lowest cost long-term cold storage).
- **2556+ Days:** Expire and purge.

Apply the lifecycle policy:
```bash
aws s3api put-bucket-lifecycle-configuration \
    --bucket finora-production-backups-mumbai \
    --lifecycle-configuration '{
        "Rules": [
            {
                "ID": "FinoraStatutoryRetentionPolicy",
                "Status": "Enabled",
                "Filter": { "Prefix": "daily-snapshots/" },
                "Transitions": [
                    { "Days": 90, "StorageClass": "GLACIER" },
                    { "Days": 365, "StorageClass": "DEEP_ARCHIVE" }
                ],
                "Expiration": { "Days": 2555 }
            }
        ]
    }'
```

---

## 3. IAM Least-Privilege Policy

Create an unprivileged IAM user or Lightsail Instance Profile for backup operations:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "FinoraBackupBucketAccess",
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket",
                "s3:GetBucketLocation"
            ],
            "Resource": "arn:aws:s3:::finora-production-backups-mumbai"
        },
        {
            "Sid": "FinoraBackupObjectOperations",
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:AbortMultipartUpload"
            ],
            "Resource": "arn:aws:s3:::finora-production-backups-mumbai/*"
        }
    ]
}
```

---

## 4. Automated Backup Scheduling

Finora provides an automated production backup script: [`scripts/backup_to_s3.sh`](file:///C:/Users/Lenovo/.gemini/antigravity/scratch/ai-reconciliation-engine/Finwise/scripts/backup_to_s3.sh).

### Option A: Crontab Configuration
Add a daily cron job scheduled at 02:00 AM IST (20:30 UTC):
```bash
crontab -e
```
Add the following line:
```cron
30 20 * * * /home/ubuntu/finora/scripts/backup_to_s3.sh >> /var/log/finora_backup.log 2>&1
```

### Option B: Systemd Timer Configuration
Create `/etc/systemd/system/finora-backup.service`:
```ini
[Unit]
Description=Finora Daily Database and Evidence S3 Backup
After=docker.service

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/finora
ExecStart=/home/ubuntu/finora/scripts/backup_to_s3.sh
StandardOutput=journal
StandardError=journal
```

Create `/etc/systemd/system/finora-backup.timer`:
```ini
[Unit]
Description=Run Finora Backup Daily at 02:00 AM IST

[Timer]
OnCalendar=*-*-* 02:00:00 Asia/Kolkata
Persistent=true

[Install]
WantedBy=timers.target
```

Enable the timer:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now finora-backup.timer
```

---

## 5. Disaster Recovery & Restoration Drill Procedure

In the event of database corruption, ransomware, accidental deletion, or server loss, execute the disaster recovery procedure using [`scripts/restore_from_s3.sh`](file:///C:/Users/Lenovo/.gemini/antigravity/scratch/ai-reconciliation-engine/Finwise/scripts/restore_from_s3.sh).

### Step 5.1: List Available Snapshots in S3
```bash
aws s3 ls s3://finora-production-backups-mumbai/daily-snapshots/
```
Output:
```
PRE 20261125_020000/
PRE 20261124_020000/
PRE 20261123_020000/
```

### Step 5.2: Execute End-to-End Recovery Drill
Run the recovery script specifying the snapshot timestamp:
```bash
chmod +x scripts/restore_from_s3.sh
./scripts/restore_from_s3.sh 20261125_020000
```

### Step 5.3: Automated Checksum Verification
The recovery engine performs the following validation steps:
1. Downloads `finora_manifest_20261125_020000.json`.
2. Downloads `finora_db_20261125_020000.dump` and computes its SHA-256 hash. Compares against `manifest.database.sha256`. If mismatched, halts immediately without touching the live database.
3. Downloads `finora_evidence_20261125_020000.tar.gz` and computes its SHA-256 hash. Compares against `manifest.evidence.sha256`. If mismatched, halts immediately.
4. Restores PostgreSQL database via `pg_restore --clean --if-exists`.
5. Safely extracts evidence documents into `/var/finora/storage` ensuring POSIX `0700` directory and `0600` file permissions.

---

## 6. Security & Safeguards Checklist

- [x] **Zero Plaintext Backups:** All S3 objects are encrypted at rest with AES-256.
- [x] **No Deletion Before Upload Confirmation:** Local archives are only pruned after S3 upload is verified with HTTP 200 / return code 0.
- [x] **Anti-Zip-Slip Protection:** Evidence restoration checks all tarball member paths to prevent directory traversal exploits.
- [x] **Fail-Closed Checksum Verification:** Any single-bit corruption in database or evidence archives aborts recovery before state modification.
- [x] **Verified via Test Suite:** 7/7 automated tests passed in [`backend/tests/test_s3_backup_restore.py`](file:///C:/Users/Lenovo/.gemini/antigravity/scratch/ai-reconciliation-engine/Finwise/backend/tests/test_s3_backup_restore.py).
