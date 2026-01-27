import * as cdk from 'aws-cdk-lib';
import * as bedrockagentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface RuntimeStackProps extends cdk.StackProps {
  environment: string;
  runtimeRole: iam.IRole;
  repository: ecr.IRepository;
  gatewayUrl: string;
  cognitoDiscoveryUrl: string;
  cognitoClientId: string;
  accountsTableName: string;
}

export class RuntimeStack extends cdk.Stack {
  public readonly runtime: bedrockagentcore.CfnRuntime;
  public readonly runtimeEndpoint: bedrockagentcore.CfnRuntimeEndpoint;

  constructor(scope: Construct, id: string, props: RuntimeStackProps) {
    super(scope, id, props);

    // AgentCore Runtime
    this.runtime = new bedrockagentcore.CfnRuntime(this, 'AgentRuntime', {
      agentRuntimeName: `centralOpsAgent${props.environment}`,
      description: 'Multi-account AWS operations agent for querying AWS resources',
      roleArn: props.runtimeRole.roleArn,
      agentRuntimeArtifact: {
        containerConfiguration: {
          containerUri: `${props.repository.repositoryUri}:v20260127154736`,
        },
      },
      networkConfiguration: {
        networkMode: 'PUBLIC',
      },
      protocolConfiguration: 'HTTP',
      environmentVariables: {
        GATEWAY_URL: props.gatewayUrl,
        AWS_REGION: this.region,
        MODEL_ID: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
        ACCOUNTS_TABLE_NAME: props.accountsTableName,
      },
      authorizerConfiguration: {
        customJwtAuthorizer: {
          discoveryUrl: props.cognitoDiscoveryUrl,
          // Cognito ID tokens have 'aud' claim (not 'client_id'), so only use allowedAudience
          allowedAudience: [props.cognitoClientId],
        },
      },
    });

    // Runtime Endpoint
    this.runtimeEndpoint = new bedrockagentcore.CfnRuntimeEndpoint(this, 'AgentRuntimeEndpoint', {
      agentRuntimeId: this.runtime.attrAgentRuntimeId,
      name: 'default',
    });
    this.runtimeEndpoint.addDependency(this.runtime);

    // Outputs
    new cdk.CfnOutput(this, 'RuntimeId', {
      value: this.runtime.attrAgentRuntimeId,
      description: 'AgentCore Runtime ID',
    });

    new cdk.CfnOutput(this, 'RuntimeArn', {
      value: this.runtime.attrAgentRuntimeArn,
      description: 'AgentCore Runtime ARN',
    });

    new cdk.CfnOutput(this, 'InvocationUrl', {
      value: `https://bedrock-agentcore.${this.region}.amazonaws.com/runtimes/${encodeURIComponent(this.runtime.attrAgentRuntimeArn)}/invocations`,
      description: 'Runtime invocation URL',
    });
  }
}
