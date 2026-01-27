// agentcore-gateway/infrastructure/lib/roles-stack.ts
import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Construct } from 'constructs';

export interface RolesStackProps extends cdk.StackProps {
  environment: string;
  bridgeLambda: lambda.IFunction;
}

export class RolesStack extends cdk.Stack {
  public readonly gatewayRole: iam.Role;
  public readonly runtimeRole: iam.Role;

  constructor(scope: Construct, id: string, props: RolesStackProps) {
    super(scope, id, props);

    // Gateway Service Role
    this.gatewayRole = new iam.Role(this, 'GatewayServiceRole', {
      roleName: `CentralOpsGatewayRole-${props.environment}`,
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
    });

    this.gatewayRole.addToPolicy(new iam.PolicyStatement({
      actions: ['lambda:InvokeFunction'],
      resources: [props.bridgeLambda.functionArn],
    }));

    // Runtime Execution Role
    this.runtimeRole = new iam.Role(this, 'RuntimeExecutionRole', {
      roleName: `CentralOpsRuntimeRole-${props.environment}`,
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
    });

    // Bedrock access
    this.runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
      resources: [`arn:aws:bedrock:${this.region}::foundation-model/anthropic.claude-*`],
    }));

    // AgentCore Identity access
    this.runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:GetWorkloadAccessToken', 'bedrock-agentcore:GetWorkloadAccessTokenForJWT'],
      resources: [
        `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default`,
        `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default/workload-identity/*`,
      ],
    }));

    // Gateway invoke access
    this.runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:InvokeGateway'],
      resources: [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:gateway/*`],
    }));

    // CloudWatch Logs access
    this.runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
      resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*`],
    }));

    // ECR access for pulling container images
    this.runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['ecr:GetAuthorizationToken'],
      resources: ['*'],
    }));
    this.runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['ecr:BatchGetImage', 'ecr:GetDownloadUrlForLayer', 'ecr:BatchCheckLayerAvailability'],
      resources: [`arn:aws:ecr:${this.region}:${this.account}:repository/central-ops-agent-*`],
    }));

    // Outputs
    new cdk.CfnOutput(this, 'GatewayRoleArn', { value: this.gatewayRole.roleArn });
    new cdk.CfnOutput(this, 'RuntimeRoleArn', { value: this.runtimeRole.roleArn });
  }
}
