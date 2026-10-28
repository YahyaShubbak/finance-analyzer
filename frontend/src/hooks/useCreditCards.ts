import { useQuery } from "@tanstack/react-query";
import { listCreditCards, listStatements } from "../api/creditCards";

export function useCreditCards() {
  return useQuery({ queryKey: ["credit-cards"], queryFn: listCreditCards });
}

export function useStatements(accountId: number | undefined) {
  return useQuery({
    queryKey: ["statements", accountId],
    queryFn: () => listStatements(accountId as number),
    enabled: accountId !== undefined,
  });
}
