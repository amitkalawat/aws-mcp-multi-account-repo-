import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface MemberAccountStackProps extends cdk.StackProps {
  centralAccountId: string;
  bridgeLambdaRoleArn: string;
}

export class MemberAccountStack extends cdk.Stack {
  public readonly targetRole: iam.Role;

  constructor(scope: Construct, id: string, props: MemberAccountStackProps) {
    super(scope, id, props);

    this.targetRole = new iam.Role(this, 'CentralOpsTargetRole', {
      roleName: 'CentralOpsTargetRole',
      assumedBy: new iam.ArnPrincipal(props.bridgeLambdaRoleArn),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('ReadOnlyAccess'),
      ],
    });

    // AWS MCP access (read-only and read-write tools)
    this.targetRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'aws-mcp:InvokeMcp',
        'aws-mcp:CallReadOnlyTool',
        'aws-mcp:CallReadWriteTool'
      ],
      resources: ['*'],
    }));

    // Add condition for central account
    const cfnRole = this.targetRole.node.defaultChild as iam.CfnRole;
    cfnRole.addPropertyOverride('AssumeRolePolicyDocument.Statement.0.Condition', {
      StringEquals: {
        'aws:PrincipalAccount': props.centralAccountId,
      },
    });

    // Outputs
    new cdk.CfnOutput(this, 'TargetRoleArn', { value: this.targetRole.roleArn });
  }
}
