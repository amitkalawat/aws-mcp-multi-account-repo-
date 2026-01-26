#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { CognitoStack } from '../lib/cognito-stack';
import { LambdaStack } from '../lib/lambda-stack';
import { RolesStack } from '../lib/roles-stack';
import * as fs from 'fs';
import * as path from 'path';

const app = new cdk.App();

const environment = app.node.tryGetContext('environment') || 'dev';
const region = app.node.tryGetContext('region') || 'us-east-1';

// Load account configuration
const configPath = path.join(__dirname, '../config/accounts.json');
let targetAccounts = '[]';
if (fs.existsSync(configPath)) {
  const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
  targetAccounts = JSON.stringify(config.accounts.filter((a: any) => a.role !== 'central'));
}

const env = { region };

// Cognito Stack
const cognitoStack = new CognitoStack(app, `CentralOps-Cognito-${environment}`, {
  environment,
  env,
});

// Lambda Stack
const lambdaStack = new LambdaStack(app, `CentralOps-Lambda-${environment}`, {
  environment,
  targetAccounts,
  env,
});

// Roles Stack (depends on Lambda)
const rolesStack = new RolesStack(app, `CentralOps-Roles-${environment}`, {
  environment,
  bridgeLambda: lambdaStack.bridgeLambda,
  env,
});
rolesStack.addDependency(lambdaStack);
