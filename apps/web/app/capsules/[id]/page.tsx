import ClientPage from "./ClientPage";

export function generateStaticParams(): { id: string }[] {
  // A non-empty build parameter is required by Next output: export. Electron's
  // loopback host maps arbitrary runtime ids to this generated client shell.
  return [{ id: "__runtime__" }];
}

export default function Page() {
  return <ClientPage />;
}
