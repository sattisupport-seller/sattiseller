import DeviceCheck
import ExpoModulesCore

// DeviceCheck: DCDevice.generateToken — токен для query_two_bits / update_two_bits на сервере (К-21).
public class SattiDeviceCheckModule: Module {
  public func definition() -> ModuleDefinition {
    Name("SattiDeviceCheck")

    Function("isSupported") { () -> Bool in
      return DCDevice.current.isSupported
    }

    AsyncFunction("generateTokenAsync") { (promise: Promise) in
      guard DCDevice.current.isSupported else {
        promise.reject("ERR_DEVICECHECK_UNSUPPORTED", "DeviceCheck is not supported on this device")
        return
      }
      DCDevice.current.generateToken { data, error in
        if let data = data {
          promise.resolve(data.base64EncodedString())
        } else {
          promise.reject("ERR_DEVICECHECK", error?.localizedDescription ?? "DeviceCheck token failed")
        }
      }
    }
  }
}
