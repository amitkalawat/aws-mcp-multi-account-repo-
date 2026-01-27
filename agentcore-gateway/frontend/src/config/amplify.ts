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
          responseType: 'code' as const,
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
