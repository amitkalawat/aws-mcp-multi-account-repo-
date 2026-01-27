# AgentCore Frontend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a React chat frontend for the AgentCore agent, hosted on S3/CloudFront with Cognito OAuth authentication.

**Architecture:** React SPA that authenticates users via Cognito Hosted UI (OAuth 2.0 PKCE flow), then sends natural language prompts to the AgentCore Runtime. The agent (running in Runtime) uses Bedrock Claude to understand queries and calls Gateway tools internally.

```
Frontend → AgentCore Runtime → AgentCore Gateway → Lambda → AWS MCP → Target Accounts
         (JWT auth)         (Workload Identity)   (SigV4)
```

The frontend is a **chat interface** - users ask questions in natural language (e.g., "List all S3 buckets in the production account") and the agent figures out which accounts and tools to use.

**Tech Stack:** React 18, TypeScript, Vite, AWS Amplify Auth, TailwindCSS, AWS CDK (TypeScript)

---

## Prerequisites

- Existing AgentCore Gateway deployed (7 stacks already running)
- Docker installed (for building agent container)
- Node.js 18+ installed
- AWS CDK bootstrapped in target region
- ECR repository created (via EcrStack)

**Note:** This plan will deploy the AgentCore Runtime with the agent container. The Runtime is required because the frontend calls the Runtime (not the Gateway directly).

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
  runtimeInvocationUrl: string;
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
        VITE_RUNTIME_URL: props.runtimeInvocationUrl,
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

// After RuntimeStack creation, add:

// Frontend Stack (requires Runtime to be deployed)
const deployFrontend = app.node.tryGetContext('deployFrontend') === 'true';
if (deployFrontend && deployRuntime) {
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
```

> **Note:** The Frontend stack requires the Runtime stack to be deployed (`-c deployRuntime=true`) because the frontend calls the Runtime, not the Gateway directly.

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

export const RUNTIME_URL = import.meta.env.VITE_RUNTIME_URL;
export const AWS_REGION = import.meta.env.VITE_AWS_REGION;
```

**Step 2: Create .env.example**

Create `agentcore-gateway/frontend/.env.example`:

```bash
# Copy from CDK output: CentralOps-Frontend-dev.FrontendConfig
VITE_COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
VITE_COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
VITE_COGNITO_DOMAIN=central-ops-dev.auth.us-east-1.amazoncognito.com
VITE_RUNTIME_URL=https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/arn%3Aaws%3Abedrock-agentcore%3A.../invocations
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

## Task 6: Create Runtime API Client

**Files:**
- Create: `agentcore-gateway/frontend/src/api/runtime.ts`
- Create: `agentcore-gateway/frontend/src/types/runtime.ts`

**Step 1: Create Runtime types**

Create `agentcore-gateway/frontend/src/types/runtime.ts`:

```typescript
export interface RuntimeRequest {
  prompt: string;
}

export interface RuntimeResponse {
  response: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}
```

**Step 2: Create Runtime API client**

Create `agentcore-gateway/frontend/src/api/runtime.ts`:

```typescript
import { RUNTIME_URL } from '../config/amplify';
import type { RuntimeRequest, RuntimeResponse } from '../types/runtime';

export async function sendPrompt(
  prompt: string,
  idToken: string
): Promise<string> {
  const request: RuntimeRequest = { prompt };

  const response = await fetch(RUNTIME_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${idToken}`,
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Runtime request failed: ${response.status} - ${errorText}`);
  }

  const data: RuntimeResponse = await response.json();
  return data.response;
}
```

**Step 3: Commit API client**

```bash
mkdir -p agentcore-gateway/frontend/src/api
mkdir -p agentcore-gateway/frontend/src/types
git add agentcore-gateway/frontend/src/api/runtime.ts
git add agentcore-gateway/frontend/src/types/runtime.ts
git commit -m "feat(frontend): add Runtime API client"
```

---

## Task 7: Create UI Components

**Files:**
- Create: `agentcore-gateway/frontend/src/components/LoginButton.tsx`
- Create: `agentcore-gateway/frontend/src/components/Header.tsx`
- Create: `agentcore-gateway/frontend/src/components/ChatMessage.tsx`
- Create: `agentcore-gateway/frontend/src/components/ChatInput.tsx`
- Create: `agentcore-gateway/frontend/src/components/ChatContainer.tsx`

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

**Step 3: Create ChatMessage component**

Create `agentcore-gateway/frontend/src/components/ChatMessage.tsx`:

```typescript
import type { ChatMessage as ChatMessageType } from '../types/runtime';

interface ChatMessageProps {
  message: ChatMessageType;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-3xl px-4 py-3 rounded-lg ${
          isUser
            ? 'bg-blue-600 text-white'
            : 'bg-gray-100 text-gray-900'
        }`}
      >
        <div className="text-xs opacity-70 mb-1">
          {isUser ? 'You' : 'Agent'}
        </div>
        <div className="whitespace-pre-wrap break-words">
          {message.content}
        </div>
      </div>
    </div>
  );
}
```

**Step 4: Create ChatInput component**

Create `agentcore-gateway/frontend/src/components/ChatInput.tsx`:

```typescript
import { useState, useRef, useEffect } from 'react';

interface ChatInputProps {
  onSend: (message: string) => void;
  isLoading: boolean;
  placeholder?: string;
}

export function ChatInput({ onSend, isLoading, placeholder }: ChatInputProps) {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [input]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      onSend(input.trim());
      setInput('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <textarea
        ref={textareaRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder || "Ask about your AWS resources..."}
        className="flex-1 resize-none rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 min-h-[48px] max-h-[200px]"
        rows={1}
        disabled={isLoading}
      />
      <button
        type="submit"
        disabled={isLoading || !input.trim()}
        className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isLoading ? (
          <span className="flex items-center gap-2">
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            Thinking...
          </span>
        ) : (
          'Send'
        )}
      </button>
    </form>
  );
}
```

**Step 5: Create ChatContainer component**

Create `agentcore-gateway/frontend/src/components/ChatContainer.tsx`:

```typescript
import { useRef, useEffect } from 'react';
import { ChatMessage } from './ChatMessage';
import { ChatInput } from './ChatInput';
import type { ChatMessage as ChatMessageType } from '../types/runtime';

interface ChatContainerProps {
  messages: ChatMessageType[];
  onSendMessage: (message: string) => void;
  isLoading: boolean;
}

export function ChatContainer({ messages, onSendMessage, isLoading }: ChatContainerProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="flex flex-col h-[calc(100vh-180px)]">
      <div className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <div className="text-center text-gray-500 mt-8">
            <p className="text-lg mb-4">Welcome to Central Ops Agent</p>
            <p className="text-sm">Ask questions about your AWS resources across accounts.</p>
            <div className="mt-6 text-left max-w-md mx-auto bg-gray-50 rounded-lg p-4">
              <p className="text-xs font-medium text-gray-700 mb-2">Example queries:</p>
              <ul className="text-xs text-gray-600 space-y-1">
                <li>"List all S3 buckets in the production account"</li>
                <li>"How many EC2 instances are running in staging?"</li>
                <li>"Show me Lambda functions in account 123456789012"</li>
                <li>"What RDS databases exist across all accounts?"</li>
              </ul>
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <ChatMessage key={message.id} message={message} />
          ))
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="border-t bg-white p-4">
        <ChatInput onSend={onSendMessage} isLoading={isLoading} />
      </div>
    </div>
  );
}
```

**Step 6: Commit UI components**

```bash
mkdir -p agentcore-gateway/frontend/src/components
git add agentcore-gateway/frontend/src/components/
git commit -m "feat(frontend): add chat UI components"
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

**Step 2: Update App.tsx with chat interface**

Replace `agentcore-gateway/frontend/src/App.tsx`:

```typescript
import { useState, useCallback } from 'react';
import { Header } from './components/Header';
import { ChatContainer } from './components/ChatContainer';
import { useAuth } from './hooks/useAuth';
import { sendPrompt } from './api/runtime';
import type { ChatMessage } from './types/runtime';

function App() {
  const { isAuthenticated, isLoading: authLoading, getIdToken } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const handleSendMessage = useCallback(async (content: string) => {
    // Add user message
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const token = await getIdToken();
      if (!token) {
        throw new Error('Not authenticated');
      }

      const response = await sendPrompt(content, token);

      // Add assistant message
      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: response,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      // Add error as assistant message
      const errorMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: `Error: ${err instanceof Error ? err.message : 'Unknown error'}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  }, [getIdToken]);

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
      <main className="max-w-4xl mx-auto">
        {isAuthenticated ? (
          <ChatContainer
            messages={messages}
            onSendMessage={handleSendMessage}
            isLoading={isLoading}
          />
        ) : (
          <div className="px-4 py-8">
            <div className="bg-white shadow rounded-lg p-6 text-center">
              <h2 className="text-lg font-medium text-gray-900 mb-4">
                Welcome to Central Ops Agent
              </h2>
              <p className="text-gray-600 mb-4">
                Sign in to chat with the agent and query AWS resources across your accounts.
              </p>
            </div>
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
git commit -m "feat(frontend): implement chat-based App for Runtime interaction"
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

**Step 1: Deploy Cognito changes (OAuth configuration)**

```bash
cd agentcore-gateway/infrastructure
npx cdk deploy CentralOps-Cognito-dev --region us-east-1
```

**Step 2: Build and push agent container**

The Runtime needs the agent container in ECR:

```bash
cd agentcore-gateway/agent

# Get ECR login and account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="us-east-1"

aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

# Build and push
docker build -t central-ops-agent .
docker tag central-ops-agent:latest $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/central-ops-agent-dev:latest
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/central-ops-agent-dev:latest
```

**Step 3: Deploy Runtime stack**

```bash
cd agentcore-gateway/infrastructure
npx cdk deploy CentralOps-Runtime-dev -c deployRuntime=true --region us-east-1
```

**Step 4: Deploy Frontend stack**

```bash
npx cdk deploy CentralOps-Frontend-dev -c deployRuntime=true -c deployFrontend=true --region us-east-1
```

**Step 5: Get configuration and create .env**

```bash
# Get frontend config from stack output
aws cloudformation describe-stacks \
  --stack-name CentralOps-Frontend-dev \
  --region us-east-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`FrontendConfig`].OutputValue' \
  --output text | jq -r 'to_entries | .[] | "\(.key)=\(.value)"' > agentcore-gateway/frontend/.env
```

**Step 6: Update Cognito callback URLs with CloudFront URL**

Get the CloudFront URL and update Cognito:

```bash
FRONTEND_URL=$(aws cloudformation describe-stacks \
  --stack-name CentralOps-Frontend-dev \
  --region us-east-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`FrontendUrl`].OutputValue' \
  --output text)

echo "CloudFront URL: $FRONTEND_URL"
# Update cognito-stack.ts callbackUrls and logoutUrls to include this URL, then redeploy:
# npx cdk deploy CentralOps-Cognito-dev --region us-east-1
```

**Step 7: Build and deploy frontend**

```bash
cd agentcore-gateway/frontend
npm install
npm run build
npm run deploy
```

**Step 8: Test the application**

1. Open the CloudFront URL in browser
2. Click "Sign In" - redirects to Cognito Hosted UI
3. Log in with test user credentials
4. Type a natural language query like: "List all S3 buckets in account 878687028155"
5. Verify the agent responds with the results

**Example queries to test:**
- "List all S3 buckets in the production account"
- "How many EC2 instances are running in account 959887439517?"
- "What Lambda functions exist in the datalake account?"

**Step 9: Final commit**

```bash
git add -A
git commit -m "feat(frontend): complete chat frontend for AgentCore Runtime"
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
| 6 | Create Runtime API Client | `runtime.ts`, `types/runtime.ts` |
| 7 | Create Chat UI Components | `ChatMessage.tsx`, `ChatInput.tsx`, `ChatContainer.tsx` |
| 8 | Create Main App | `App.tsx`, `main.tsx` |
| 9 | Add Deploy Scripts | `deploy.sh`, `package.json` |
| 10 | Deploy and Test | Build agent container, CDK deploy Runtime + Frontend |

**Total estimated tasks:** 10 major tasks with ~55 individual steps

## Architecture Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (React)                               │
│  - Chat interface for natural language queries                              │
│  - Authenticates via Cognito OAuth (PKCE)                                   │
│  - Sends prompts to Runtime                                                 │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ POST { "prompt": "..." }
                                    │ Authorization: Bearer <JWT>
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AGENTCORE RUNTIME (Container)                        │
│  - Runs central_ops_agent.py                                                │
│  - Uses Bedrock Claude to understand queries                                │
│  - Calls Gateway tools to query AWS resources                               │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ Workload Identity Token
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AGENTCORE GATEWAY                                 │
│  - Routes tool calls to Lambda target                                       │
│  - Automatic SigV4 signing                                                  │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ SigV4
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            LAMBDA BRIDGE                                    │
│  - Assumes role in target account                                           │
│  - Calls AWS MCP Server                                                     │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ SigV4 (assumed credentials)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AWS MCP SERVER                                    │
│  - Executes AWS CLI commands                                                │
│  - Returns results                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```
