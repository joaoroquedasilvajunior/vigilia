import Link from "next/link";
import { notFound } from "next/navigation";
import { getClusterMembers, type ClusterMember } from "@/lib/api";

function MemberRow({ m }: { m: ClusterMember }) {
  return (
    <Link
      href={`/deputados/${m.id}`}
      className="flex items-center gap-3 p-3 rounded-xl border border-gray-100 hover:border-blue-300 hover:bg-blue-50/40 transition-all group"
    >
      {m.photo_url ? (
        <img
          src={m.photo_url}
          alt={m.name}
          className="w-10 h-10 rounded-full object-cover ring-1 ring-gray-200"
        />
      ) : (
        <div className="w-10 h-10 rounded-full bg-gray-200 flex items-center justify-center text-gray-500 text-sm font-bold">
          {m.name.charAt(0)}
        </div>
      )}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 group-hover:text-blue-700 transition-colors line-clamp-1">
          {m.name}
        </p>
        <p className="text-xs text-gray-500">
          {m.party ?? "—"} · {m.state_uf ?? "—"}
        </p>
      </div>
    </Link>
  );
}

export default async function CoalicaoMembersPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let data;
  try {
    data = await getClusterMembers(id);
  } catch {
    notFound();
  }

  const cohesionPct = data.cohesion_score
    ? `${Math.round(data.cohesion_score * 100)}%`
    : "—";

  return (
    <main className="max-w-5xl mx-auto px-4 py-8">
      <Link
        href="/coalicoes"
        className="text-sm text-blue-600 hover:underline mb-4 inline-block"
      >
        ← Todas as coalizões
      </Link>

      <h1 className="text-2xl font-bold text-gray-900 mb-1">
        {data.cluster_label ?? "Coalizão"}
      </h1>
      <p className="text-gray-500 text-sm mb-6">
        {data.member_count ?? data.members.length} deputados · cohesão {cohesionPct}
      </p>

      {data.members.length === 0 ? (
        <p className="text-gray-400 text-sm">Nenhum membro nesta coalizão.</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {data.members.map((m) => (
            <MemberRow key={m.id} m={m} />
          ))}
        </div>
      )}
    </main>
  );
}
