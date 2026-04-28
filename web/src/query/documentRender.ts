import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { axiosInstance } from "#root/constant.ts";

const RenderedBlock = z.object({
	id: z.string(),
	bbox: z.array(z.number()).length(4),
	line_height: z.number(),
	font_family: z.string(),
	font_size: z.number(),
	color: z.string(),
	html: z.string(),
});

const RenderedPage = z.object({
	bg_url: z.string(),
	width: z.int32().positive(),
	height: z.int32().positive(),
	blocks: z.array(RenderedBlock),
});

const RenderedDocument = z.object({
	id: z.string(),
	pages: z.array(RenderedPage),
});

export const useQueryRenderedDocument = (
	chatId: string,
	enabled: boolean = true,
) =>
	useQuery({
		queryKey: [chatId],
		enabled: enabled,
		queryFn: async () => {
			const response = await axiosInstance.get(`/chats/${chatId}/render`);
			return await RenderedDocument.parseAsync(response.data);
		},
	});
