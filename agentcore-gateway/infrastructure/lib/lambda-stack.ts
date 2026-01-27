import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import * as path from 'path';

export interface LambdaStackProps extends cdk.StackProps {
  environment: string;
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
    // Lambda can assume CentralOpsTargetRole in any account
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

    // Lambda function - simple bridge, no account config needed
    this.bridgeLambda = new lambda.Function(this, 'BridgeLambda', {
      functionName: `aws-mcp-bridge-${props.environment}`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../lambda')),
      role: this.bridgeLambdaRole,
      timeout: cdk.Duration.seconds(120),
      memorySize: 256,
      // No environment variables needed - Lambda is a simple bridge
      // Account management is handled by the agent via DynamoDB
      logRetention: logs.RetentionDays.TWO_WEEKS,
    });

    // Outputs
    new cdk.CfnOutput(this, 'BridgeLambdaArn', { value: this.bridgeLambda.functionArn });
    new cdk.CfnOutput(this, 'BridgeLambdaRoleArn', { value: this.bridgeLambdaRole.roleArn });
  }
}
