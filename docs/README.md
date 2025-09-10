# Webex Contact Center BYOVA Gateway Documentation

Welcome to the comprehensive documentation for the Webex Contact Center BYOVA (Bring Your Own Virtual Agent) Gateway. This gateway enables seamless integration between Webex Contact Center and various virtual agent providers, including AWS Lex.

## 📚 Setup Guides

### Complete Integration Guide
- **[BYOVA with AWS Lex Setup Guide](guides/byova-aws-lex-setup.md)** - Step-by-step guide for setting up voice AI with Webex Contact Center and AWS Lex

This comprehensive guide covers:
- Setting up a Webex Contact Center sandbox
- Configuring BYOVA and BYODS (Bring Your Own Data Source)
- Creating and configuring AWS Lex bots
- Deploying and configuring the BYOVA Gateway
- Testing your voice AI integration end-to-end

## 🚀 Quick Start

For a quick test of the gateway with local audio:

1. **Clone and Setup**
   ```bash
   git clone https://github.com/webex/webex-byova-gateway-python.git
   cd webex-byova-gateway-python
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Generate gRPC Stubs**
   ```bash
   python -m grpc_tools.protoc -I./proto --python_out=src/generated --grpc_python_out=src/generated proto/*.proto
   ```

3. **Start the Gateway**
   ```bash
   python main.py
   ```

4. **Access Monitoring Interface**
   - Open http://localhost:8080 in your browser

## 🏗️ Architecture

The BYOVA Gateway follows a modular architecture:

- **gRPC Server**: Handles communication with Webex Contact Center
- **Virtual Agent Router**: Routes requests to appropriate connector implementations
- **Connectors**: Support for various virtual agent platforms
  - Local Audio Connector (for testing)
  - AWS Lex Connector (for production)
- **Web Monitoring Interface**: Real-time dashboard for monitoring and debugging

## 🔧 Configuration

The gateway is configured via `config/config.yaml`. Key configuration areas:

- **Gateway Settings**: Host, port, and basic configuration
- **Connectors**: Virtual agent connector configurations
- **Monitoring**: Web interface settings
- **Logging**: Log levels and file management
- **Sessions**: Session management and cleanup

## 📖 API Reference

### gRPC Endpoints
- **ListVirtualAgents**: Returns available virtual agents
- **ProcessCallerInput**: Handles bidirectional streaming for voice interactions

### HTTP Endpoints
- `GET /`: Main dashboard
- `GET /api/status`: Gateway status
- `GET /api/connections`: Connection data
- `GET /health`: Health check
- `GET /api/debug/sessions`: Debug information

## 🔌 Connectors

### Local Audio Connector
- **Purpose**: Testing and development with pre-recorded audio files
- **Configuration**: Audio file mapping and agent definitions
- **Use Case**: Initial testing and validation

### AWS Lex Connector
- **Purpose**: Production integration with Amazon Lex v2
- **Features**: Real-time voice AI, intent recognition, slot filling
- **Configuration**: AWS credentials, bot settings, audio processing

## 🛠️ Development

### Adding New Connectors
1. Create a new connector class in `src/connectors/`
2. Inherit from `IVendorConnector`
3. Implement required abstract methods
4. Add configuration to `config/config.yaml`
5. Restart the server

### Testing
- Use the local audio connector for initial testing
- Monitor real-time data via the web interface
- Check logs for conversation flow and error conditions

## 📞 Support

For questions about BYOVA integration:
- Check the troubleshooting section in the setup guide
- Review the gateway logs and monitoring interface
- Consult the AWS Lex and Webex Contact Center documentation
- Reach out to the developer community for assistance

## 📄 License

[Cisco Sample Code License v1.1](LICENSE) © 2018 Cisco and/or its affiliates

---

**Note**: This Sample Code is not supported by Cisco TAC and is not tested for quality or performance. This is intended for example purposes only and is provided by Cisco "AS IS" with all faults and without warranty or support of any kind.
