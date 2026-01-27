#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { CognitoStack } from '../lib/cognito-stack';
import { LambdaStack } from '../lib/lambda-stack';
import { RolesStack } from '../lib/roles-stack';
import { MemberAccountStack } from '../lib/member-account-stack';
import { EcrStack } from '../lib/ecr-stack';
import { RuntimeStack } from '../lib/runtime-stack';
import { GatewayStack } from '../lib/gateway-stack';
import { DynamoDBStack } from '../lib/dynamodb-stack';
import { FrontendStack } from '../lib/frontend-stack';

const app = new cdk.App();

const environment = app.node.tryGetContext('environment') || 'dev';
const region = app.node.tryGetContext('region') || 'us-east-1';
const organizationId = app.node.tryGetContext('organizationId');

const env = { region };

// DynamoDB Stack for account mappings
// Agent queries this table to get account list and map names to IDs
const dynamodbStack = new DynamoDBStack(app, `CentralOps-DynamoDB-${environment}`, {
  environment,
  env,
});

// Cognito Stack
const cognitoStack = new CognitoStack(app, `CentralOps-Cognito-${environment}`, {
  environment,
  env,
});

// Lambda Stack - simple bridge, no account config needed
const lambdaStack = new LambdaStack(app, `CentralOps-Lambda-${environment}`, {
  environment,
  organizationId,
  env,
});

// Roles Stack (depends on Lambda)
const rolesStack = new RolesStack(app, `CentralOps-Roles-${environment}`, {
  environment,
  bridgeLambda: lambdaStack.bridgeLambda,
  env,
});
rolesStack.addDependency(lambdaStack);

// Grant Runtime role access to DynamoDB accounts table
dynamodbStack.accountsTable.grantReadData(rolesStack.runtimeRole);

// Member Account Stack (target role for same account setup)
// Deploy this to each member account that needs to be queried
// centralAccountId: Pass via context or use current account
const centralAccountId = app.node.tryGetContext('centralAccountId') || process.env.CDK_DEFAULT_ACCOUNT;
const memberStack = new MemberAccountStack(app, `CentralOps-MemberRole-${environment}`, {
  centralAccountId: centralAccountId!,
  bridgeLambdaRoleArn: lambdaStack.bridgeLambdaRole.roleArn,
  env,
});
memberStack.addDependency(lambdaStack);

// ECR Stack for Agent container
const ecrStack = new EcrStack(app, `CentralOps-ECR-${environment}`, {
  environment,
  env,
});

// Gateway Stack
const gatewayStack = new GatewayStack(app, `CentralOps-Gateway-${environment}`, {
  environment,
  gatewayRole: rolesStack.gatewayRole,
  bridgeLambda: lambdaStack.bridgeLambda,
  cognitoDiscoveryUrl: cognitoStack.discoveryUrl,
  cognitoClientId: cognitoStack.userPoolClient.userPoolClientId,
  env,
});
gatewayStack.addDependency(rolesStack);
gatewayStack.addDependency(lambdaStack);
gatewayStack.addDependency(cognitoStack);

// Runtime Stack for AgentCore Runtime
// Set deployRuntime context to 'true' to deploy (requires container image in ECR)
const deployRuntime = app.node.tryGetContext('deployRuntime') === 'true';
let runtimeStack: RuntimeStack | undefined;
if (deployRuntime) {
  runtimeStack = new RuntimeStack(app, `CentralOps-Runtime-${environment}`, {
    environment,
    runtimeRole: rolesStack.runtimeRole,
    repository: ecrStack.repository,
    gatewayUrl: gatewayStack.gatewayUrl,
    cognitoDiscoveryUrl: cognitoStack.discoveryUrl,
    cognitoClientId: cognitoStack.userPoolClient.userPoolClientId,
    accountsTableName: dynamodbStack.accountsTable.tableName,
    env,
  });
  runtimeStack.addDependency(rolesStack);
  runtimeStack.addDependency(ecrStack);
  runtimeStack.addDependency(cognitoStack);
  runtimeStack.addDependency(gatewayStack);
  runtimeStack.addDependency(dynamodbStack);
}

// Frontend Stack (requires Runtime to be deployed)
const deployFrontend = app.node.tryGetContext('deployFrontend') === 'true';
if (deployFrontend && deployRuntime && runtimeStack) {
  const frontendStack = new FrontendStack(app, `CentralOps-Frontend-${environment}`, {
    environment,
    runtimeInvocationUrl: `https://bedrock-agentcore.${region}.amazonaws.com/runtimes/${encodeURIComponent(runtimeStack.runtime.attrAgentRuntimeArn)}/invocations`,
    cognitoUserPoolId: cognitoStack.userPool.userPoolId,
    cognitoClientId: cognitoStack.userPoolClient.userPoolClientId,
    cognitoDomain: `central-ops-${environment}.auth.${region}.amazoncognito.com`,
    env,
  });
  frontendStack.addDependency(runtimeStack);
  frontendStack.addDependency(cognitoStack);
}
