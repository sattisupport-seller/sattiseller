Pod::Spec.new do |s|
  s.name           = 'SattiDeviceCheck'
  s.version        = '1.0.0'
  s.summary        = 'Apple DeviceCheck token for Satti Seller'
  s.description    = 'Generates a DeviceCheck token; the server reads and sets two bits at Apple.'
  s.author         = ''
  s.homepage       = 'https://example.invalid'
  s.license        = 'UNLICENSED'
  s.platforms      = { :ios => '15.1' }
  s.source         = { git: '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'
  s.frameworks = 'DeviceCheck'

  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
  }

  s.source_files = '**/*.{h,m,mm,swift}'
end
