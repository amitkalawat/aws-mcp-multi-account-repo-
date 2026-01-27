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
