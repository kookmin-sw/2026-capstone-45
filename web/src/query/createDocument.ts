import { useMutation } from "@tanstack/react-query";
import { axiosInstance, queryClient } from "#root/constant.ts";

export const useMutateCreateDocument = () =>
	useMutation({
		mutationFn: async (file: File) => {
			const formData = new FormData();
			formData.append("file", file);

			const result = await axiosInstance.post("/documents", formData, {
				headers: {
					"Content-Type": "multipart/form-data",
				},
			});

			return result.data;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["useQueryDocumentList"] });
		},
	});
