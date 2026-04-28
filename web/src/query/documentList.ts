import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { axiosInstance } from "../constant";

export const DocumentListEntry = z.object({
	doc_id: z.int32(),
	display_name: z.string(),
	pages_cnt: z.int32(),
	process_status: z.string(),
	process_log: z.string(),
});

export type Document = z.infer<typeof DocumentListEntry>;

const ListDocumentResponse = z.object({
	docs: z.array(DocumentListEntry),
});

export const useQueryDocumentList = () =>
	useQuery({
		queryKey: ["useQueryDocumentList"],
		queryFn: async () => {
			const response = await axiosInstance.get("/documents");
			return await ListDocumentResponse.parseAsync(response.data);
		},
	});
