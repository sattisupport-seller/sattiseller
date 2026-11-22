/** @type {import('jest').Config} */
module.exports = {
  preset: 'jest-expo',
  testMatch: ['**/src/**/*.test.ts', '**/src/**/*.test.tsx'],
  // lucide-react-native в пакете отдаётся как ES-модуль для react-native; тестам нужна CommonJS-сборка
  moduleNameMapper: {
    '^lucide-react-native$': '<rootDir>/node_modules/lucide-react-native/dist/cjs/lucide-react-native.js',
  },
};
