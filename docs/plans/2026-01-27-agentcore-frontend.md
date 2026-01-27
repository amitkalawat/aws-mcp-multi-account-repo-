# AgentCore Frontend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a React frontend for the AgentCore Gateway agent, hosted on S3/CloudFront with Cognito OAuth authentication.

**Architecture:** React SPA that authenticates users via Cognito Hosted UI (OAuth 2.0 PKCE flow), then calls the AgentCore Gateway directly with JWT tokens. The frontend is hosted on S3 as a static website, distributed via CloudFront for HTTPS and caching.

**Tech Stack:** React 18, TypeScript, Vite, AWS Amplify Auth, TailwindCSS, AWS CDK (TypeScript)

---

## Prerequisites

- Existing AgentCore Gateway deployed (7 stacks already running)
- Node.js 18+ installed
- AWS CDK bootstrapped in target region

---

## Task 1: Update Cognito Stack for OAuth

**Files:**
- Modify: `agentcore-gateway/infrastructure/lib/cognito-stack.ts`

**Step 1: Add OAuth configuration to Cognito User Pool Client**

Update the Cognito stack to enable OAuth flows and configure callback URLs.

```typescript
// In cognito-stack.ts, update the UserPoolClient configuration

// Add domain for hosted UI (after UserPool creation)
const userPoolDomain = new cognito.UserPoolDomain(this, 'UserPoolDomain', {
  userPool: this.userPool,
  cognitoDomain: {
    domainPrefix: `central-ops-${props.environment}`,
  },
});

// Update UserPoolClient to include OAuth settings
this.userPoolClient = new cognito.UserPoolClient(this, 'UserPoolClient', {
  userPool: this.userPool,
  userPoolClientName: `central-ops-client-${props.environment}`,
  generateSecret: false,
  authFlows: {
    userPassword: true,
    userSrp: true,
  },
  oAuth: {
    flows: {
      authorizationCodeGrant: true,
    },
    scopes: [
      cognito.OAuthScope.OPENID,
      cognito.OAuthScope.EMAIL,
      cognito.OAuthScope.PROFILE,
    ],
    callbackUrls: [
      'http://localhost:5173/',  // Vite dev server
      `https://${props.environment}-central-ops.example.com/`,  // Placeholder, updated after CloudFront deploy
    ],
    logoutUrls: [
      'http://localhost:5173/',
      `https://${props.environment}-central-ops.example.com/`,
    ],
  },
  idTokenValidity: cdk.Duration.hours(1),
  accessTokenValidity: cdk.Duration.hours(1),
  refreshTokenValidity: cdk.Duration.days(30),
});

// Add output for hosted UI domain
new cdk.CfnOutput(this, 'UserPoolDomain', {
  value: `${userPoolDomain.domainName}.auth.${cdk.Aws.REGION}.amazoncognito.com`,
  description: 'Cognito Hosted UI Domain',
});
```

**Step 2: Run CDK diff to verify changes**

Run: `cd agentcore-gateway/infrastructure && npx cdk diff CentralOps-Cognito-dev`
Expected: Shows UserPoolDomain addition and UserPoolClient OAuth configuration changes

**Step 3: Commit Cognito changes**

```bash
git add agentcore-gateway/infrastructure/lib/cognito-stack.ts
git commit -m "feat(cognito): add OAuth configuration for frontend"
```

---

## Task 2: Create Frontend CDK Stack

**Files:**
- Create: `agentcore-gateway/infrastructure/lib/frontend-stack.ts`
- Modify: `agentcore-gateway/infrastructure/bin/infrastructure.ts`

**Step 1: Create the frontend stack file**

Create `agentcore-gateway/infrastructure/lib/frontend-stack.ts`:

```typescript
import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import * as path from 'path';

export interface FrontendStackProps extends cdk.StackProps {
  environment: string;
  gatewayUrl: string;
  cognitoUserPoolId: string;
  cognitoClientId: string;
  cognitoDomain: string;
}

export class FrontendStack extends cdk.Stack {
  public readonly distribution: cloudfront.Distribution;
  public readonly bucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: FrontendStackProps) {
    super(scope, id, props);

    // S3 bucket for static website hosting
    this.bucket = new s3.Bucket(this, 'FrontendBucket', {
      bucketName: `central-ops-frontend-${props.environment}-${this.account}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // Origin Access Identity for CloudFront
    const originAccessIdentity = new cloudfront.OriginAccessIdentity(this, 'OAI', {
      comment: `OAI for central-ops-frontend-${props.environment}`,
    });

    // Grant CloudFront access to S3
    this.bucket.addToResourcePolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject'],
      resources: [this.bucket.arnForObjects('*')],
      principals: [new iam.CanonicalUserPrincipal(
        originAccessIdentity.cloudFrontOriginAccessIdentityS3CanonicalUserId
      )],
    }));

    // CloudFront distribution
    this.distribution = new cloudfront.Distribution(this, 'Distribution', {
      defaultBehavior: {
        origin: new origins.S3Origin(this.bucket, {
          originAccessIdentity,
        }),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
      },
      defaultRootObject: 'index.html',
      errorResponses: [
        {
          httpStatus: 403,
          responseHttpStatus: 200,
          responsePagePath: '/index.html',
          ttl: cdk.Duration.minutes(5),
        },
        {
          httpStatus: 404,
          responseHttpStatus: 200,
          responsePagePath: '/index.html',
          ttl: cdk.Duration.minutes(5),
        },
      ],
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
    });

    // Outputs
    new cdk.CfnOutput(this, 'FrontendUrl', {
      value: `https://${this.distribution.distributionDomainName}`,
      description: 'Frontend CloudFront URL',
    });

    new cdk.CfnOutput(this, 'BucketName', {
      value: this.bucket.bucketName,
      description: 'Frontend S3 Bucket',
    });

    new cdk.CfnOutput(this, 'DistributionId', {
      value: this.distribution.distributionId,
      description: 'CloudFront Distribution ID',
    });

    // Output config for frontend app
    new cdk.CfnOutput(this, 'FrontendConfig', {
      value: JSON.stringify({
        VITE_COGNITO_USER_POOL_ID: props.cognitoUserPoolId,
        VITE_COGNITO_CLIENT_ID: props.cognitoClientId,
        VITE_COGNITO_DOMAIN: props.cognitoDomain,
        VITE_GATEWAY_URL: props.gatewayUrl,
        VITE_AWS_REGION: this.region,
      }),
      description: 'Frontend environment configuration (copy to .env)',
    });
  }
}
```

**Step 2: Add frontend stack to infrastructure.ts**

Add to `agentcore-gateway/infrastructure/bin/infrastructure.ts`:

```typescript
import { FrontendStack } from '../lib/frontend-stack';

// After GatewayStack creation, add:

// Frontend Stack
const deployFrontend = app.node.tryGetContext('deployFrontend') === 'true';
if (deployFrontend) {
  const frontendStack = new FrontendStack(app, `CentralOps-Frontend-${environment}`, {
    environment,
    gatewayUrl: gatewayStack.gatewayUrl,
    cognitoUserPoolId: cognitoStack.userPool.userPoolId,
    cognitoClientId: cognitoStack.userPoolClient.userPoolClientId,
    cognitoDomain: `central-ops-${environment}.auth.${region}.amazoncognito.com`,
    env,
  });
  frontendStack.addDependency(gatewayStack);
  frontendStack.addDependency(cognitoStack);
}
```

**Step 3: Verify CDK compiles**

Run: `cd agentcore-gateway/infrastructure && npm run build`
Expected: No TypeScript errors

**Step 4: Commit frontend stack**

```bash
git add agentcore-gateway/infrastructure/lib/frontend-stack.ts
git add agentcore-gateway/infrastructure/bin/infrastructure.ts
git commit -m "feat(infra): add frontend S3/CloudFront stack"
```

---

## Task 3: Initialize React Application

**Files:**
- Create: `agentcore-gateway/frontend/` (entire directory)

**Step 1: Create React app with Vite**

```bash
cd agentcore-gateway
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

**Step 2: Install dependencies**

```bash
npm install @aws-amplify/auth aws-amplify
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

**Step 3: Configure Tailwind**

Update `agentcore-gateway/frontend/tailwind.config.js`:

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

**Step 4: Add Tailwind to CSS**

Replace `agentcore-gateway/frontend/src/index.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  @apply bg-gray-50 text-gray-900;
}
```

**Step 5: Commit React app initialization**

```bash
git add agentcore-gateway/frontend
git commit -m "feat(frontend): initialize React app with Vite and Tailwind"
```

---

## Task 4: Create Amplify Auth Configuration

**Files:**
- Create: `agentcore-gateway/frontend/src/config/amplify.ts`
- Create: `agentcore-gateway/frontend/.env.example`

**Step 1: Create Amplify config file**

Create `agentcore-gateway/frontend/src/config/amplify.ts`:

```typescript
import { Amplify } from 'aws-amplify';

const config = {
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
      userPoolClientId: import.meta.env.VITE_COGNITO_CLIENT_ID,
      loginWith: {
        oauth: {
          domain: import.meta.env.VITE_COGNITO_DOMAIN,
          scopes: ['openid', 'email', 'profile'],
          redirectSignIn: [window.location.origin + '/'],
          redirectSignOut: [window.location.origin + '/'],
          responseType: 'code',
        },
      },
    },
  },
};

export function configureAmplify() {
  Amplify.configure(config);
}

export const GATEWAY_URL = import.meta.env.VITE_GATEWAY_URL;
export const AWS_REGION = import.meta.env.VITE_AWS_REGION;
```

**Step 2: Create .env.example**

Create `agentcore-gateway/frontend/.env.example`:

```bash
# Copy from CDK output: CentralOps-Frontend-dev.FrontendConfig
VITE_COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
VITE_COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
VITE_COGNITO_DOMAIN=central-ops-dev.auth.us-east-1.amazoncognito.com
VITE_GATEWAY_URL=https://xxxxxxxx.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp
VITE_AWS_REGION=us-east-1
```

**Step 3: Add .env to .gitignore**

```bash
echo ".env" >> agentcore-gateway/frontend/.gitignore
echo ".env.local" >> agentcore-gateway/frontend/.gitignore
```

**Step 4: Commit Amplify config**

```bash
git add agentcore-gateway/frontend/src/config/amplify.ts
git add agentcore-gateway/frontend/.env.example
git add agentcore-gateway/frontend/.gitignore
git commit -m "feat(frontend): add Amplify auth configuration"
```

---

## Task 5: Create Auth Context and Hook

**Files:**
- Create: `agentcore-gateway/frontend/src/context/AuthContext.tsx`
- Create: `agentcore-gateway/frontend/src/hooks/useAuth.ts`

**Step 1: Create Auth Context**

Create `agentcore-gateway/frontend/src/context/AuthContext.tsx`:

```typescript
import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { getCurrentUser, signOut, fetchAuthSession, AuthUser } from 'aws-amplify/auth';
import { Hub } from 'aws-amplify/utils';

interface AuthContextType {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  idToken: string | null;
  signOut: () => Promise<void>;
  getIdToken: () => Promise<string | null>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [idToken, setIdToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const checkUser = async () => {
    try {
      const currentUser = await getCurrentUser();
      setUser(currentUser);
      const session = await fetchAuthSession();
      const token = session.tokens?.idToken?.toString() || null;
      setIdToken(token);
    } catch {
      setUser(null);
      setIdToken(null);
    } finally {
      setIsLoading(false);
    }
  };

  const getIdToken = async (): Promise<string | null> => {
    try {
      const session = await fetchAuthSession({ forceRefresh: false });
      return session.tokens?.idToken?.toString() || null;
    } catch {
      return null;
    }
  };

  const handleSignOut = async () => {
    await signOut();
    setUser(null);
    setIdToken(null);
  };

  useEffect(() => {
    checkUser();

    const hubListener = Hub.listen('auth', ({ payload }) => {
      switch (payload.event) {
        case 'signedIn':
          checkUser();
          break;
        case 'signedOut':
          setUser(null);
          setIdToken(null);
          break;
      }
    });

    return () => hubListener();
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        idToken,
        signOut: handleSignOut,
        getIdToken,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
```

**Step 2: Create useAuth hook (re-export)**

Create `agentcore-gateway/frontend/src/hooks/useAuth.ts`:

```typescript
export { useAuth } from '../context/AuthContext';
```

**Step 3: Commit auth context**

```bash
mkdir -p agentcore-gateway/frontend/src/context
mkdir -p agentcore-gateway/frontend/src/hooks
git add agentcore-gateway/frontend/src/context/AuthContext.tsx
git add agentcore-gateway/frontend/src/hooks/useAuth.ts
git commit -m "feat(frontend): add auth context and hook"
```

---

## Task 6: Create Gateway API Client

**Files:**
- Create: `agentcore-gateway/frontend/src/api/gateway.ts`
- Create: `agentcore-gateway/frontend/src/types/gateway.ts`

**Step 1: Create Gateway types**

Create `agentcore-gateway/frontend/src/types/gateway.ts`:

```typescript
export interface MCPRequest {
  jsonrpc: '2.0';
  id: number;
  method: 'tools/call';
  params: {
    name: string;
    arguments: Record<string, unknown>;
  };
}

export interface MCPResponse {
  jsonrpc: '2.0';
  id: number;
  result?: {
    isError: boolean;
    content: Array<{
      type: string;
      text: string;
    }>;
  };
  error?: {
    code: number;
    message: string;
  };
}

export interface QueryParams {
  accountId: string;
  toolName: string;
  arguments?: Record<string, unknown>;
  region?: string;
}

export interface Account {
  account_id: string;
  name: string;
  environment: string;
  description?: string;
  enabled: boolean;
}
```

**Step 2: Create Gateway API client**

Create `agentcore-gateway/frontend/src/api/gateway.ts`:

```typescript
import { GATEWAY_URL } from '../config/amplify';
import type { MCPRequest, MCPResponse, QueryParams } from '../types/gateway';

let requestId = 0;

export async function queryGateway(
  params: QueryParams,
  idToken: string
): Promise<MCPResponse> {
  const request: MCPRequest = {
    jsonrpc: '2.0',
    id: ++requestId,
    method: 'tools/call',
    params: {
      name: 'bridge-lambda___query',
      arguments: {
        account_id: params.accountId,
        tool_name: params.toolName,
        arguments: params.arguments || {},
        region: params.region || 'us-east-1',
      },
    },
  };

  const response = await fetch(GATEWAY_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${idToken}`,
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Gateway request failed: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

export function parseGatewayResponse(response: MCPResponse): string {
  if (response.error) {
    throw new Error(response.error.message);
  }

  if (!response.result?.content?.[0]?.text) {
    return 'No response content';
  }

  try {
    // The response is nested JSON - parse it
    const outerText = response.result.content[0].text;
    const outerJson = JSON.parse(outerText);

    if (outerJson.result?.content?.[0]?.text) {
      const innerText = outerJson.result.content[0].text;
      const innerJson = JSON.parse(innerText);

      // Return formatted response or raw content
      if (innerJson.content?.result) {
        return JSON.stringify(innerJson.content.result, null, 2);
      }
      if (innerJson.response) {
        return innerJson.response;
      }
      return JSON.stringify(innerJson, null, 2);
    }

    return JSON.stringify(outerJson, null, 2);
  } catch {
    return response.result.content[0].text;
  }
}
```

**Step 3: Commit API client**

```bash
mkdir -p agentcore-gateway/frontend/src/api
mkdir -p agentcore-gateway/frontend/src/types
git add agentcore-gateway/frontend/src/api/gateway.ts
git add agentcore-gateway/frontend/src/types/gateway.ts
git commit -m "feat(frontend): add Gateway API client"
```

---

## Task 7: Create UI Components

**Files:**
- Create: `agentcore-gateway/frontend/src/components/LoginButton.tsx`
- Create: `agentcore-gateway/frontend/src/components/QueryForm.tsx`
- Create: `agentcore-gateway/frontend/src/components/ResponseDisplay.tsx`
- Create: `agentcore-gateway/frontend/src/components/Header.tsx`

**Step 1: Create LoginButton component**

Create `agentcore-gateway/frontend/src/components/LoginButton.tsx`:

```typescript
import { signInWithRedirect } from 'aws-amplify/auth';
import { useAuth } from '../hooks/useAuth';

export function LoginButton() {
  const { isAuthenticated, user, signOut, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="text-gray-500">Loading...</div>
    );
  }

  if (isAuthenticated) {
    return (
      <div className="flex items-center gap-4">
        <span className="text-sm text-gray-600">
          {user?.signInDetails?.loginId || 'User'}
        </span>
        <button
          onClick={signOut}
          className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-md hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500"
        >
          Sign Out
        </button>
      </div>
    );
  }

  return (
    <button
      onClick={() => signInWithRedirect()}
      className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
    >
      Sign In
    </button>
  );
}
```

**Step 2: Create Header component**

Create `agentcore-gateway/frontend/src/components/Header.tsx`:

```typescript
import { LoginButton } from './LoginButton';

export function Header() {
  return (
    <header className="bg-white shadow">
      <div className="max-w-7xl mx-auto px-4 py-4 sm:px-6 lg:px-8 flex justify-between items-center">
        <h1 className="text-2xl font-bold text-gray-900">
          Central Ops Agent
        </h1>
        <LoginButton />
      </div>
    </header>
  );
}
```

**Step 3: Create QueryForm component**

Create `agentcore-gateway/frontend/src/components/QueryForm.tsx`:

```typescript
import { useState } from 'react';

interface QueryFormProps {
  onSubmit: (accountId: string, toolName: string, cliCommand?: string) => void;
  isLoading: boolean;
}

export function QueryForm({ onSubmit, isLoading }: QueryFormProps) {
  const [accountId, setAccountId] = useState('');
  const [toolName, setToolName] = useState('aws___list_regions');
  const [cliCommand, setCliCommand] = useState('aws s3 ls');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(accountId, toolName, toolName === 'aws___call_aws' ? cliCommand : undefined);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label htmlFor="accountId" className="block text-sm font-medium text-gray-700">
          Account ID
        </label>
        <input
          type="text"
          id="accountId"
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
          placeholder="123456789012"
          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2"
          required
        />
      </div>

      <div>
        <label htmlFor="toolName" className="block text-sm font-medium text-gray-700">
          Tool
        </label>
        <select
          id="toolName"
          value={toolName}
          onChange={(e) => setToolName(e.target.value)}
          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2"
        >
          <option value="aws___list_regions">List Regions</option>
          <option value="aws___call_aws">AWS CLI Command</option>
        </select>
      </div>

      {toolName === 'aws___call_aws' && (
        <div>
          <label htmlFor="cliCommand" className="block text-sm font-medium text-gray-700">
            AWS CLI Command
          </label>
          <input
            type="text"
            id="cliCommand"
            value={cliCommand}
            onChange={(e) => setCliCommand(e.target.value)}
            placeholder="aws s3 ls"
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm border p-2 font-mono"
            required
          />
          <p className="mt-1 text-xs text-gray-500">
            Must start with "aws" (e.g., "aws s3 ls", "aws ec2 describe-instances")
          </p>
        </div>
      )}

      <button
        type="submit"
        disabled={isLoading}
        className="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isLoading ? 'Querying...' : 'Query'}
      </button>
    </form>
  );
}
```

**Step 4: Create ResponseDisplay component**

Create `agentcore-gateway/frontend/src/components/ResponseDisplay.tsx`:

```typescript
interface ResponseDisplayProps {
  response: string | null;
  error: string | null;
}

export function ResponseDisplay({ response, error }: ResponseDisplayProps) {
  if (error) {
    return (
      <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-md">
        <h3 className="text-sm font-medium text-red-800">Error</h3>
        <pre className="mt-2 text-sm text-red-700 whitespace-pre-wrap">{error}</pre>
      </div>
    );
  }

  if (!response) {
    return null;
  }

  return (
    <div className="mt-4 p-4 bg-gray-50 border border-gray-200 rounded-md">
      <h3 className="text-sm font-medium text-gray-800">Response</h3>
      <pre className="mt-2 text-sm text-gray-700 whitespace-pre-wrap overflow-x-auto max-h-96 overflow-y-auto">
        {response}
      </pre>
    </div>
  );
}
```

**Step 5: Commit UI components**

```bash
mkdir -p agentcore-gateway/frontend/src/components
git add agentcore-gateway/frontend/src/components/
git commit -m "feat(frontend): add UI components"
```

---

## Task 8: Create Main App Component

**Files:**
- Modify: `agentcore-gateway/frontend/src/App.tsx`
- Modify: `agentcore-gateway/frontend/src/main.tsx`

**Step 1: Update main.tsx to include providers**

Replace `agentcore-gateway/frontend/src/main.tsx`:

```typescript
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import { configureAmplify } from './config/amplify';
import { AuthProvider } from './context/AuthContext';

// Configure Amplify before rendering
configureAmplify();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </React.StrictMode>
);
```

**Step 2: Update App.tsx**

Replace `agentcore-gateway/frontend/src/App.tsx`:

```typescript
import { useState } from 'react';
import { Header } from './components/Header';
import { QueryForm } from './components/QueryForm';
import { ResponseDisplay } from './components/ResponseDisplay';
import { useAuth } from './hooks/useAuth';
import { queryGateway, parseGatewayResponse } from './api/gateway';

function App() {
  const { isAuthenticated, isLoading: authLoading, getIdToken } = useAuth();
  const [response, setResponse] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isQuerying, setIsQuerying] = useState(false);

  const handleQuery = async (accountId: string, toolName: string, cliCommand?: string) => {
    setIsQuerying(true);
    setError(null);
    setResponse(null);

    try {
      const token = await getIdToken();
      if (!token) {
        throw new Error('Not authenticated');
      }

      const args: Record<string, unknown> = {};
      if (toolName === 'aws___call_aws' && cliCommand) {
        args.cli_command = cliCommand;
      }

      const result = await queryGateway(
        { accountId, toolName, arguments: args },
        token
      );

      const parsed = parseGatewayResponse(result);
      setResponse(parsed);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setIsQuerying(false);
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-lg text-gray-600">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="max-w-3xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        {isAuthenticated ? (
          <div className="bg-white shadow rounded-lg p-6">
            <h2 className="text-lg font-medium text-gray-900 mb-4">
              Query AWS Accounts
            </h2>
            <QueryForm onSubmit={handleQuery} isLoading={isQuerying} />
            <ResponseDisplay response={response} error={error} />
          </div>
        ) : (
          <div className="bg-white shadow rounded-lg p-6 text-center">
            <h2 className="text-lg font-medium text-gray-900 mb-4">
              Welcome to Central Ops Agent
            </h2>
            <p className="text-gray-600 mb-4">
              Sign in to query AWS resources across your accounts.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
```

**Step 3: Commit app changes**

```bash
git add agentcore-gateway/frontend/src/App.tsx
git add agentcore-gateway/frontend/src/main.tsx
git commit -m "feat(frontend): implement main App with query functionality"
```

---

## Task 9: Add Build and Deploy Scripts

**Files:**
- Create: `agentcore-gateway/frontend/scripts/deploy.sh`
- Modify: `agentcore-gateway/frontend/package.json`

**Step 1: Create deploy script**

Create `agentcore-gateway/frontend/scripts/deploy.sh`:

```bash
#!/bin/bash
set -e

# Configuration
REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"

echo "=== Building frontend ==="
npm run build

echo "=== Getting stack outputs ==="
BUCKET_NAME=$(aws cloudformation describe-stacks \
  --stack-name "CentralOps-Frontend-${ENVIRONMENT}" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`BucketName`].OutputValue' \
  --output text)

DISTRIBUTION_ID=$(aws cloudformation describe-stacks \
  --stack-name "CentralOps-Frontend-${ENVIRONMENT}" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`DistributionId`].OutputValue' \
  --output text)

echo "Bucket: $BUCKET_NAME"
echo "Distribution: $DISTRIBUTION_ID"

echo "=== Syncing to S3 ==="
aws s3 sync dist/ "s3://${BUCKET_NAME}/" --delete --region "$REGION"

echo "=== Invalidating CloudFront cache ==="
aws cloudfront create-invalidation \
  --distribution-id "$DISTRIBUTION_ID" \
  --paths "/*"

echo "=== Done ==="
FRONTEND_URL=$(aws cloudformation describe-stacks \
  --stack-name "CentralOps-Frontend-${ENVIRONMENT}" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`FrontendUrl`].OutputValue' \
  --output text)

echo "Frontend available at: $FRONTEND_URL"
```

**Step 2: Make script executable**

```bash
chmod +x agentcore-gateway/frontend/scripts/deploy.sh
```

**Step 3: Add scripts to package.json**

Update `agentcore-gateway/frontend/package.json` scripts section:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "lint": "eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0",
    "preview": "vite preview",
    "deploy": "./scripts/deploy.sh"
  }
}
```

**Step 4: Commit deploy scripts**

```bash
mkdir -p agentcore-gateway/frontend/scripts
git add agentcore-gateway/frontend/scripts/deploy.sh
git add agentcore-gateway/frontend/package.json
git commit -m "feat(frontend): add build and deploy scripts"
```

---

## Task 10: Deploy and Test

**Step 1: Deploy Cognito changes**

```bash
cd agentcore-gateway/infrastructure
npx cdk deploy CentralOps-Cognito-dev --region us-east-1
```

**Step 2: Deploy Frontend stack**

```bash
npx cdk deploy CentralOps-Frontend-dev -c deployFrontend=true --region us-east-1
```

**Step 3: Get configuration and create .env**

```bash
# Get frontend config from stack output
aws cloudformation describe-stacks \
  --stack-name CentralOps-Frontend-dev \
  --region us-east-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`FrontendConfig`].OutputValue' \
  --output text | jq -r 'to_entries | .[] | "\(.key)=\(.value)"' > agentcore-gateway/frontend/.env
```

**Step 4: Update Cognito callback URLs**

Get the CloudFront URL and update Cognito:

```bash
FRONTEND_URL=$(aws cloudformation describe-stacks \
  --stack-name CentralOps-Frontend-dev \
  --region us-east-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`FrontendUrl`].OutputValue' \
  --output text)

echo "Update Cognito callback URLs to include: $FRONTEND_URL"
# Manual step: Update CognitoStack callbackUrls and logoutUrls, then redeploy
```

**Step 5: Build and deploy frontend**

```bash
cd agentcore-gateway/frontend
npm install
npm run build
npm run deploy
```

**Step 6: Test the application**

1. Open the CloudFront URL in browser
2. Click "Sign In" - redirects to Cognito Hosted UI
3. Log in with test user credentials
4. Enter an account ID and run a query
5. Verify response displays correctly

**Step 7: Final commit**

```bash
git add -A
git commit -m "feat(frontend): complete frontend implementation"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Update Cognito for OAuth | `cognito-stack.ts` |
| 2 | Create Frontend CDK Stack | `frontend-stack.ts`, `infrastructure.ts` |
| 3 | Initialize React App | `frontend/` directory |
| 4 | Create Amplify Config | `amplify.ts`, `.env.example` |
| 5 | Create Auth Context | `AuthContext.tsx`, `useAuth.ts` |
| 6 | Create Gateway API Client | `gateway.ts`, `types/gateway.ts` |
| 7 | Create UI Components | `LoginButton.tsx`, `QueryForm.tsx`, etc. |
| 8 | Create Main App | `App.tsx`, `main.tsx` |
| 9 | Add Deploy Scripts | `deploy.sh`, `package.json` |
| 10 | Deploy and Test | CDK deploy + frontend deploy |

**Total estimated tasks:** 10 major tasks with ~50 individual steps
