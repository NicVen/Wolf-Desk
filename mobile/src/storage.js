import AsyncStorage from '@react-native-async-storage/async-storage';

const K_URL = 'wolf.baseUrl';
const K_PASS = 'wolf.pass';

export const DEFAULT_URL = 'https://wolf-desk-production.up.railway.app';

export async function loadSettings() {
  try {
    const [url, pass] = await Promise.all([
      AsyncStorage.getItem(K_URL),
      AsyncStorage.getItem(K_PASS),
    ]);
    return { baseUrl: url || DEFAULT_URL, pass: pass || '' };
  } catch (e) {
    return { baseUrl: DEFAULT_URL, pass: '' };
  }
}

export async function saveSettings({ baseUrl, pass }) {
  try {
    await AsyncStorage.multiSet([
      [K_URL, baseUrl || DEFAULT_URL],
      [K_PASS, pass || ''],
    ]);
  } catch (e) {
    /* non-fatal: settings just won't persist across restarts */
  }
}
