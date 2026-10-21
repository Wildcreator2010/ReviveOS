"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { hasSession } from "../../src/api/client";
import { logout } from "../../src/api/auth";

export function AuthMenu() {
  const router = useRouter();
  const [authenticated, setAuthenticated] = useState(false);

  useEffect(() => {
    const update = () => setAuthenticated(hasSession());
    update();
    window.addEventListener("revive-session", update);
    return () => window.removeEventListener("revive-session", update);
  }, []);

  if (!authenticated) {
    return (
      <Link className="btn small" href="/login/">
        登录
      </Link>
    );
  }
  return (
    <button
      type="button"
      className="btn small"
      onClick={() => {
        void logout().finally(() => router.replace("/login/"));
      }}
    >
      退出登录
    </button>
  );
}
