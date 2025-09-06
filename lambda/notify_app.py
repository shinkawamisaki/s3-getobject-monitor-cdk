# SPDX-License-Identifier: MIT
# Copyright (c) 2025 <shinkawa>
# lambda/notify_app.py
import json, os, urllib.parse, urllib.request
from datetime import datetime
import boto3

# ===== Slack =====
def _get_webhook_url() -> str:
    name = os.environ["SLACK_SECRET_NAME"]
    s = boto3.client("secretsmanager").get_secret_value(SecretId=name)["SecretString"]
    try:
        return json.loads(s)["url"]
    except Exception:
        return s

def _post_to_slack(text: str):
    url = _get_webhook_url()
    data = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5): pass

# ===== Mask helpers =====
MASK_IP = os.environ.get("MASK_IP", "true").lower() == "true"
MASK_ACCESS_KEY = os.environ.get("MASK_ACCESS_KEY", "true").lower() == "true"
MASK_ACCOUNT_ID = os.environ.get("MASK_ACCOUNT_ID", "true").lower() == "true"

def _mask_ip(ip: str) -> str:
    if not ip: return "-"
    if not MASK_IP: return ip
    if ip.count(".") == 3:
        a,b,c,_ = ip.split("."); return f"{a}.{b}.{c}.0/24"
    if ":" in ip:
        parts = ip.split(":"); return ":".join(parts[:4] + ["0000"]*4) + "/64"
    return ip

def _mask_access_key(key: str) -> str:
    return ("***"+key[-4:]) if (MASK_ACCESS_KEY and key) else (key or "-")

def _mask_arn_account(arn: str) -> str:
    if not arn or ":" not in arn: return arn or "-"
    if not MASK_ACCOUNT_ID: return arn
    p = arn.split(":")
    if len(p) >= 5: p[4] = "************"  # ARN内のアカIDは完全伏せ
    return ":".join(p)

def _format_account_id(acct: str) -> str:
    if not acct: return ""
    if not MASK_ACCOUNT_ID: return acct
    return f"{acct[:2]}***{acct[-4:]}"  # 例: 97***4140

# ===== Robot / Human 判定 =====
EMOJI_HUMAN = os.environ.get("EMOJI_HUMAN", ":inbox_tray:")
EMOJI_ROBOT = os.environ.get("EMOJI_ROBOT", ":robot_face:")
TREAT_CLI_AS_HUMAN = os.environ.get("TREAT_CLI_AS_HUMAN", "false").lower() == "true"

def _is_likely_automated(user_identity: dict, user_agent: str) -> bool:
    ui_type = (user_identity or {}).get("type") or ""
    arn = (user_identity or {}).get("arn", "") or ""
    role = arn.split("/")[-2] if "assumed-role/" in arn else ""
    ua = (user_agent or "").lower()
    if any(t in ua for t in ("aws-sdk","botocore","boto3","aws-cli","curl","wget","go-http-client","python-urllib")) and not TREAT_CLI_AS_HUMAN:
        return True
    if ui_type in ("AWSService","AssumedRole"): return True
    if role in {"ecsTaskExecutionRole","AWSServiceRoleForECS","AWSServiceRoleForEC2"}: return True
    return False

# ===== Handler =====
def handler(event, context):
    d = (event or {}).get("detail") or {}
    req = d.get("requestParameters") or {}
    ui  = d.get("userIdentity") or {}

    ev   = d.get("eventName") or "GetObject"
    src  = d.get("eventSource") or "s3.amazonaws.com"
    acct = d.get("recipientAccountId") or ""
    acct_disp = _format_account_id(acct)
    when = d.get("eventTime") or datetime.utcnow().isoformat() + "Z"

    bucket = req.get("bucketName")
    key = req.get("key") or (req.get("object") or {}).get("key")
    if key: key = urllib.parse.unquote(key)

    ip = _mask_ip(d.get("sourceIPAddress"))
    ua = d.get("userAgent") or "-"

    utype = ui.get("type") or "-"
    uarn  = _mask_arn_account(ui.get("arn") or "-")
    aks   = _mask_access_key(ui.get("accessKeyId"))

    robot = _is_likely_automated(ui, ua)
    prefix = f"{EMOJI_ROBOT} *S3 GetObject from Task*" if robot else f"{EMOJI_HUMAN} *S3 GetObject detected*"

    lines = [prefix, f"- *Time:* {when}"]
    if bucket: lines.append(f"- *Bucket:* `{bucket}`")
    if key:    lines.append(f"- *Key:* `{key}`")
    lines += [
        f"- *IP:* `{ip}`",
        f"- *UserAgent:* `{ua}`",
        f"- *UserIdentity.type:* `{utype}`",
        f"- *UserIdentity.arn:* `{uarn}`",
        f"- *AccessKeyId:* `{aks}`",
        f"- *Event:* `{ev}` via `{src}`" + (f" (Account `{acct_disp}`)" if acct_disp else ""),
    ]

    _post_to_slack("\n".join(lines))
    return {"ok": True}
