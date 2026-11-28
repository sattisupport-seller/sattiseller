/** @type {import('jest').Config} */
module.exports = {
  preset: 'jest-expo',
  testMatch: ['**/src/**/*.test.ts', '**/src/**/*.test.tsx'],
  // К-33 А7: первый рендер тяжёлых экранов (склад) на холодном кэше ноутбука с 8 ГБ памяти занимает больше
  // стандартных 5 с — release_check падал по таймауту, а не по логике. 30 с с запасом; зависший тест всё равно упадёт.
  testTimeout: 30_000,
  // lucide-react-native в пакете отдаётся как ES-модуль для react-native; тестам нужна CommonJS-сборка
  moduleNameMapper: {
    '^lucide-react-native$': '<rootDir>/node_modules/lucide-react-native/dist/cjs/lucide-react-native.js',
  },
};
