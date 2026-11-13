
import { McpServer } from "@modelcontextprotocol/server";
import { createMcpHandler } from "agents/mcp/server";
import { z } from "zod";

function createServer() {
  const server = new McpServer({
    name: "christian-reels-factory",
    version: "0.2.0",
  });

  server.registerTool(
    "project_status",
    {
      description: "Check the project status.",
    },
    async (_ctx) => ({
      content: [
        {
          type: "text",
          text: "Christian Reels Factory MCP server is running.",
        },
      ],
    })
  );

  server.registerTool(
    "generate_script",
    {
      description: "Generate a structured Arabic Christian Reel script.",
      inputSchema: z.object({
        topic: z.string().min(3).describe("Reel topic"),
        bible_reference: z.string().optional(),
        key_message: z.string().optional(),
        duration_seconds: z.number().int().min(20).max(60).optional(),
      }),
    },
    async ({
      topic,
      bible_reference,
      key_message,
      duration_seconds,
    }) => {
      const duration = duration_seconds ?? 35;

      const hook = `هل فكرت يومًا في معنى ${topic} في حياتك؟`;

      const body = key_message
        ? key_message
        : `تأمل في ${topic}. أحيانًا نمر بمواقف تجعلنا ننسى أن الإيمان والرجاء يمنحان القلب قوة للاستمرار.`;

      const reflection =
        "خذ لحظة وراجع قلبك، واجعل هذه الرسالة بداية لتغيير إيجابي في حياتك.";

      const ending =
        "ثق في محبة الله، ولا تفقد رجاءك. شارك الرسالة مع شخص يحتاج أن يسمعها اليوم.";

      const referenceLine = bible_reference
        ? `المرجع الكتابي المقترح: ${bible_reference}\nيرجى مراجعة نص الآية من نسخة الكتاب المقدس المعتمدة قبل التسجيل.`
        : "يمكن إضافة مرجع كتابي موثوق يدعم موضوع الريل.";

      const script = [
        "CHRISTIAN REEL SCRIPT",
        `الموضوع: ${topic}`,
        `المدة المستهدفة: ${duration} ثانية`,
        "",
        "البداية:",
        hook,
        "",
        "الرسالة:",
        body,
        "",
        "التأمل:",
        reflection,
        "",
        "الخاتمة:",
        ending,
        "",
        "المرجع:",
        referenceLine,
        "",
        "الوصف:",
        `${topic} | رسالة روحية قصيرة للتأمل والرجاء.`,
        "",
        "#الكتاب_المقدس_مسموع #تأملات_مسيحية #كلمة_الله",
      ].join("\n");

      return {
        content: [
          {
            type: "text",
            text: script,
          },
        ],
      };
    }
  );

  return server;
}

const handler = createMcpHandler(createServer);

export default {
  fetch(request, env, ctx) {
    return handler(request, env, ctx);
  },
} satisfies ExportedHandler;
