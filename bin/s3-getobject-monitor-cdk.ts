/*
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2025 <Your Name or Org>
 */
import * as cdk from 'aws-cdk-lib';
import { S3GetObjectMonitorStack } from '../lib/s3-getobject-monitor-cdk-stack';

const app = new cdk.App();

const appName = process.env.APP_NAME ?? 'GetObjectMonitor-A';
const buckets = (process.env.BUCKET_NAMES ?? '').split(/[\s,]+/).filter(Boolean);
const slackSecretName = process.env.SLACK_SECRET_NAME ?? '';

if (buckets.length === 0 || !slackSecretName) {
  console.error('Set BUCKET_NAMES and SLACK_SECRET_NAME before "cdk deploy".');
  process.exit(1);
}

new S3GetObjectMonitorStack(app, 'S3GetObjectMonitor', {
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION ?? 'ap-northeast-1' },
  appName,
  bucketNames: buckets,
  slackSecretName,
});
