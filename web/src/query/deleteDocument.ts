import { useMutation, useQueryClient } from "@tanstack/react-query";
import { axiosInstance } from "#root/constant.ts";

export const useMutationDeleteDocument = () => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn: async (docId: number) => {
			await axiosInstance.delete(`/documents/${docId}`);
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["useQueryDocumentList"] });
		},
	});
};
