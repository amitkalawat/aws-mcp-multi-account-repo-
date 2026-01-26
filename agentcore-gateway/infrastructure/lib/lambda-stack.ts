// agentcore-gateway/infrastructure/lib/lambda-stack.ts
import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import * as path from 'path';

export interface LambdaStackProps extends cdk.StackProps {
  environment: string;
  targetAccounts: string; // JSON string
  organizationId?: string;
}

export class LambdaStack extends cdk.Stack {
  public readonly bridgeLambda: lambda.Function;
  public readonly bridgeLambdaRole: iam.Role;

  constructor(scope: Construct, id: string, props: LambdaStackProps) {
    super(scope, id, props);

    // Lambda execution role
    this.bridgeLambdaRole = new iam.Role(this, 'BridgeLambdaRole', {
      roleName: `CentralOpsBridgeRole-${props.environment}`,
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });

    // Cross-account assume role policy
    const assumeRolePolicy = new iam.PolicyStatement({
      actions: ['sts:AssumeRole'],
      resources: ['arn:aws:iam::*:role/CentralOpsTargetRole'],
    });
    if (props.organizationId) {
      assumeRolePolicy.addCondition('StringEquals', {
        'aws:PrincipalOrgID': props.organizationId,
      });
    }
    this.bridgeLambdaRole.addToPolicy(assumeRolePolicy);

    // AWS MCP access policy
    this.bridgeLambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: ['aws-mcp:InvokeMcp', 'aws-mcp:CallReadOnlyTool'],
      resources: ['*'],
    }));

    // Lambda function
    this.bridgeLambda = new lambda.Function(this, 'BridgeLambda', {
      functionName: `aws-mcp-bridge-${props.environment}`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../lambda')),
      role: this.bridgeLambdaRole,
      timeout: cdk.Duration.seconds(120),
      memorySize: 256,
      environment: {
        TARGET_ACCOUNTS: props.targetAccounts,
        TARGET_ROLE_NAME: 'CentralOpsTargetRole',
      },
      logRetention: logs.RetentionDays.TWO_WEEKS,
    });

    // Outputs
    new cdk.CfnOutput(this, 'LambdaArn', { value: this.bridgeLambda.functionArn });
    new cdk.CfnOutput(this, 'LambdaRoleArn', { value: this.bridgeLambdaRole.roleArn });
  }
}
