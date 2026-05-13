import { useMutation } from "@tanstack/react-query";
import { axiosInstance, queryClient } from "#root/constant.ts";

interface RenameDocumentParam {
	docId: number;
	displayName: string;
}

export const useMutationRenameDocument = () =>
	useMutation<unknown, unknown, RenameDocumentParam>({
		mutationFn: async ({ docId, displayName }) => {
			await axiosInstance.put(`/documents/${docId}`, {
				display_name: displayName,
			});
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["useQueryDocumentList"] });
		},
	});
