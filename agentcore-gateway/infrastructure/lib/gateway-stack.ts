import * as cdk from 'aws-cdk-lib';
import * as bedrockagentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Construct } from 'constructs';

export interface GatewayStackProps extends cdk.StackProps {
  environment: string;
  gatewayRole: iam.IRole;
  bridgeLambda: lambda.IFunction;
  cognitoDiscoveryUrl: string;
  cognitoClientId: string;
}

export class GatewayStack extends cdk.Stack {
  public readonly gateway: bedrockagentcore.CfnGateway;
  public readonly gatewayTarget: bedrockagentcore.CfnGatewayTarget;
  public readonly gatewayUrl: string;

  constructor(scope: Construct, id: string, props: GatewayStackProps) {
    super(scope, id, props);

    // AgentCore Gateway
    this.gateway = new bedrockagentcore.CfnGateway(this, 'Gateway', {
      name: `centralOpsGateway${props.environment}`,
      description: 'Gateway for multi-account AWS operations agent',
      roleArn: props.gatewayRole.roleArn,
      protocolType: 'MCP',
      authorizerType: 'CUSTOM_JWT',
      authorizerConfiguration: {
        customJwtAuthorizer: {
          discoveryUrl: props.cognitoDiscoveryUrl,
          // Cognito ID tokens have 'aud' claim set to the client ID
          // Only configure allowedAudience - ID tokens don't have client_id claim
          allowedAudience: [props.cognitoClientId],
        },
      },
    });

    // Gateway Target (Lambda Bridge)
    this.gatewayTarget = new bedrockagentcore.CfnGatewayTarget(this, 'LambdaTarget', {
      gatewayIdentifier: this.gateway.attrGatewayIdentifier,
      name: 'bridge-lambda',
      description: 'Lambda bridge for AWS MCP Server access',
      targetConfiguration: {
        mcp: {
          lambda: {
            lambdaArn: props.bridgeLambda.functionArn,
            toolSchema: {
              // Only expose the query tool - account management is done by agent via DynamoDB
              inlinePayload: [
                {
                  name: 'query',
                  description: 'Query a specific AWS account using AWS MCP Server tools. The agent must provide the account_id from its account registry (DynamoDB).',
                  inputSchema: {
                    type: 'object',
                    properties: {
                      account_id: { type: 'string', description: 'AWS account ID to query' },
                      tool_name: { type: 'string', description: 'AWS MCP tool name to invoke (e.g., aws___list_regions, aws___call_aws)' },
                      arguments: { type: 'object', description: 'Arguments for the MCP tool' },
                      region: { type: 'string', description: 'AWS region for the query (default: us-east-1)' },
                    },
                    required: ['account_id', 'tool_name'],
                  },
                },
              ],
            },
          },
        },
      },
      credentialProviderConfigurations: [
        {
          credentialProviderType: 'GATEWAY_IAM_ROLE',
        },
      ],
    });
    this.gatewayTarget.addDependency(this.gateway);

    // Use the native Gateway URL attribute
    this.gatewayUrl = this.gateway.attrGatewayUrl;

    // Outputs
    new cdk.CfnOutput(this, 'GatewayId', {
      value: this.gateway.attrGatewayIdentifier,
      description: 'AgentCore Gateway ID',
    });

    new cdk.CfnOutput(this, 'GatewayUrl', {
      value: this.gatewayUrl,
      description: 'AgentCore Gateway URL',
    });

    new cdk.CfnOutput(this, 'TargetId', {
      value: this.gatewayTarget.attrTargetId,
      description: 'Gateway Target ID',
    });
  }
}
