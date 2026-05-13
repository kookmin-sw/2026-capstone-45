import { useMutation } from "@tanstack/react-query";
import { axiosInstance, queryClient } from "#root/constant.ts";

interface RenameChatParam {
	chatId: string;
	displayName: string;
}

export const useMutationRenameChat = () =>
	useMutation<unknown, unknown, RenameChatParam>({
		mutationFn: async ({ chatId, displayName }) => {
			await axiosInstance.put(`/chats/${chatId}`, {
				display_name: displayName,
			});
		},
		onSuccess: (_, { chatId }) => {
			queryClient.invalidateQueries({ queryKey: ["useQueryChatList"] });
			queryClient.invalidateQueries({
				queryKey: ["useQueryChatDetail", chatId],
			});
		},
	});
