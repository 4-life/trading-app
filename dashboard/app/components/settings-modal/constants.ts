// The keys each provider needs (the API's exchange_api.FIELDS), with labels.
export const PROVIDER_FIELDS: Record<string, Record<string, string>> = {
  hyperliquid: {
    api_wallet_private_key: 'API wallet private key',
    account_address: 'Account address',
  },
  lighter: {
    api_key_private_key: 'API key private key',
    account_index: 'Account index',
    api_key_index: 'API key index',
  },
};
