import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

const RenderedBlock = z.object({
	id: z.string(),
	bbox: z.array(z.number()).length(4),
	line_height: z.number(),
	font_family: z.string(),
	font_size: z.number(),
	color: z.string(),
	html: z.string(),
});

export type TRenderedBlock = z.infer<typeof RenderedBlock>;

const RenderedPage = z.object({
	bg_url: z.string(),
	width: z.int32().positive(),
	height: z.int32().positive(),
	blocks: z.array(RenderedBlock),
});

export type TRenderedPage = z.infer<typeof RenderedPage>;

const RenderedDocument = z.object({
	id: z.string(),
	pages: z.array(RenderedPage),
});

export type TRenderedDocument = z.infer<typeof RenderedDocument>;

export const useQueryRenderedDocument = (id: string) =>
	useQuery({
		queryKey: [id],
		queryFn: async () => {
			const response = await fetch("/debug_finish.json");
			if (!response.ok) {
				throw new Error("Network response was not ok");
			}
			const decoded = await response.json();
			return await RenderedDocument.parseAsync(decoded);
		},
	});
