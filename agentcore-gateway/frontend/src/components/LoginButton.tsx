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
