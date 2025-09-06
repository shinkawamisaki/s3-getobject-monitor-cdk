/*
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2025 <Your Name or Org>
 */
import {
  Stack, StackProps, Duration, CfnOutput,
  aws_iam as iam, aws_logs as logs, aws_lambda as lambda,
  aws_events as events, aws_events_targets as targets,
  aws_cloudtrail as cloudtrail, aws_s3 as s3,
} from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as path from 'path';

interface Props extends StackProps {
  appName: string;
  bucketNames: string[];
  slackSecretName: string;
}

export class S3GetObjectMonitorStack extends Stack {
  constructor(scope: Construct, id: string, props: Props) {
    super(scope, id, props);

    // --- Lambda 実行ロール ---
    const role = new iam.Role(this, 'LambdaRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });
    // Secrets Manager 参照を最小権限付与（特定Secret名のみ）
    role.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [`arn:aws:secretsmanager:${this.region}:${this.account}:secret:${props.slackSecretName}*`],
    }));

    // --- Slack通知 Lambda ---
    const fn = new lambda.Function(this, 'Fn', {
      functionName: props.appName,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'notify_app.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda')),
      role,
      timeout: Duration.seconds(5),
      memorySize: 128,
      logRetention: logs.RetentionDays.ONE_YEAR,
      environment: {
        SLACK_SECRET_NAME: props.slackSecretName,
        MASK_IP: 'true',
        MASK_ACCESS_KEY: 'true',
        VERBOSE_USER_AGENT: 'false',
        REGION: this.region,
      },
    });

    // --- EventBridge ルール（複数バケット） ---
    const rule = new events.Rule(this, 'Rule', {
      ruleName: props.appName,
      eventPattern: {
        source: ['aws.s3'],
        detailType: ['AWS API Call via CloudTrail'],
        detail: {
          eventSource: ['s3.amazonaws.com'],
          eventName: ['GetObject'],
          requestParameters: { bucketName: props.bucketNames },
        },
      },
    });
    rule.addTarget(new targets.LambdaFunction(fn));

    // --- CloudTrail（毎回“専用”を新規作成。マージや既存参照なし！） ---
    const targetBuckets = props.bucketNames.map((name, i) =>
      s3.Bucket.fromBucketName(this, `TargetBucket${i}`, name),
    );
    const trail = new cloudtrail.Trail(this, 'Trail', {
      trailName: `${props.appName}-Trail`,
      isMultiRegionTrail: true,
      includeGlobalServiceEvents: true,
    });
    for (const b of targetBuckets) {
      trail.addS3EventSelector(
        [{ bucket: b, objectPrefix: '' }],
        { readWriteType: cloudtrail.ReadWriteType.READ_ONLY, includeManagementEvents: true },
      );
    }

    new CfnOutput(this, 'FunctionName', { value: fn.functionName });
    new CfnOutput(this, 'RuleName', { value: rule.ruleName! });
    new CfnOutput(this, 'TrailArn', { value: trail.trailArn });
  }
}