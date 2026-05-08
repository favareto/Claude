import { db } from "@/lib/db";
import { ContentEditor } from "@/components/admin/ContentEditor";

export default async function AdminContentPage() {
  const contents = await db.siteContent.findMany();
  const contentMap = Object.fromEntries(contents.map((c) => [c.key, c.value]));

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Conteúdo do site</h1>
        <p className="text-gray-500 mt-1">
          Edite os textos e informações que aparecem na página inicial para os visitantes
        </p>
      </div>
      <ContentEditor initialContent={contentMap} />
    </div>
  );
}
