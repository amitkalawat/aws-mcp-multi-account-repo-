import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';

export interface DynamoDBStackProps extends cdk.StackProps {
  environment: string;
}

export class DynamoDBStack extends cdk.Stack {
  public readonly accountsTable: dynamodb.Table;

  constructor(scope: Construct, id: string, props: DynamoDBStackProps) {
    super(scope, id, props);

    // Account mappings table
    // Schema:
    //   PK: account_id (string) - AWS account ID
    //   name: string - Human-readable name (e.g., "Production")
    //   environment: string - Environment type (e.g., "prod", "staging", "dev")
    //   enabled: boolean - Whether this account is active for queries
    //   tags: map - Optional tags/metadata
    this.accountsTable = new dynamodb.Table(this, 'AccountsTable', {
      tableName: `central-ops-accounts-${props.environment}`,
      partitionKey: {
        name: 'account_id',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY, // For dev; use RETAIN for prod
      pointInTimeRecovery: true,
    });

    // GSI for querying by environment
    this.accountsTable.addGlobalSecondaryIndex({
      indexName: 'by-environment',
      partitionKey: {
        name: 'environment',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // Outputs
    new cdk.CfnOutput(this, 'AccountsTableName', {
      value: this.accountsTable.tableName,
      exportName: `CentralOps-AccountsTable-${props.environment}`,
    });

    new cdk.CfnOutput(this, 'AccountsTableArn', {
      value: this.accountsTable.tableArn,
      exportName: `CentralOps-AccountsTableArn-${props.environment}`,
    });
  }
}
