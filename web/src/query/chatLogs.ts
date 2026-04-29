import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { axiosInstance } from "#root/constant.ts";

export const LogEvent = z
	.object({
		time: z.string().nullish(),
		ts: z.number().nullish(),
		run_id: z.string().nullish(),
		component: z.string(),
		event: z.string(),
		duration_ms: z.number().nullish(),
		payload: z.unknown().nullish(),
	})
	.passthrough();

export const ChatLogsResponse = z.object({
	chat_id: z.int32(),
	status: z.string(),
	summary: z.record(z.string(), z.unknown()),
	latest_event: LogEvent.nullish(),
	events: z.array(LogEvent),
	files: z.object({
		llm: z.array(z.string()),
		search: z.array(z.string()),
		retrieval: z.array(z.string()),
		output: z.array(z.string()),
	}),
});

export type LogEvent = z.infer<typeof LogEvent>;
export type ChatLogsResponse = z.infer<typeof ChatLogsResponse>;

export const useQueryChatLogs = (chatId: number, enabled = true) =>
	useQuery({
		queryKey: ["useQueryChatLogs", chatId],
		queryFn: async () => {
			const result = await axiosInstance.get(`/chats/${chatId}/logs`);
			return await ChatLogsResponse.parseAsync(result.data);
		},
		enabled,
		refetchInterval: (query) => {
			const status = query.state.data?.status;
			return status === "running" || status === "created" ? 1000 : 5000;
		},
	});

export const useQueryChatLogFile = (
	chatId: number,
	path: string | null,
	enabled = true,
) =>
	useQuery({
		queryKey: ["useQueryChatLogFile", chatId, path],
		queryFn: async () => {
			const result = await axiosInstance.get(`/chats/${chatId}/logs/file`, {
				params: { path },
				responseType: "text",
				transformResponse: [(data) => data],
			});
			return result.data as string;
		},
		enabled: enabled && path !== null,
	});
