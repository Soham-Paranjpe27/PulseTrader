import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="mt-16 text-center">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <Link href="/" className="text-primary mt-3 inline-block text-sm hover:underline">
        Back to home
      </Link>
    </div>
  );
}
