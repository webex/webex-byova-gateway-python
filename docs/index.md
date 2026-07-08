---
layout: default
title: Webex Contact Center BYOVA Gateway
---

# Webex Contact Center BYOVA Gateway

Welcome to the documentation for the Webex Contact Center BYOVA (Bring Your Own Virtual Agent) Gateway. This gateway connects Webex Contact Center to local audio, AWS Lex, and Google CX Agent Studio virtual agents.

## 🚀 Quick Start

Choose the setup guide for your virtual-agent provider:

- **[AWS Lex Setup Guide](https://developer.webex.com/webex-contact-center/docs/byova-and-aws-lex)**
- **[Google CX Agent Studio Setup Guide](guides/byova-gecx-setup.md)**

These guides cover:
- Setting up a Webex Contact Center sandbox
- Configuring BYOVA and BYODS (Bring Your Own Data Source)
- Connecting AWS Lex or Google CX Agent Studio
- Deploying and testing the gateway

## 🏗️ What You'll Build

A functional voice AI system where customers can:
- Call your contact center
- Interact with an AWS Lex or CX Agent Studio virtual agent
- Seamlessly transfer to human agents when needed

## 🔧 Key Features

- **gRPC Integration**: Seamless communication with Webex Contact Center
- **Modular Architecture**: Easy to extend with new virtual agent providers
- **Real-time Monitoring**: Web dashboard for debugging and monitoring
- **Multiple Connectors**: Local audio, AWS Lex, and GECX/CX Agent Studio support
- **Comprehensive Logging**: Detailed logs for troubleshooting and analysis

## 📚 Documentation

- **[AWS Lex Setup Guide](https://developer.webex.com/webex-contact-center/docs/byova-and-aws-lex)** - AWS integration walkthrough
- **[GECX Setup Guide](guides/byova-gecx-setup.md)** - Google CX Agent Studio integration walkthrough
- **[gRPC Interface](../proto/README.md)** - BYOVA protocol definitions and stub generation
- **[GitHub Repository](https://github.com/webex/webex-byova-gateway-python)** - Source code and issues

## 🛠️ Development

This gateway serves as a **functional example** for customers implementing BYOVA integrations. It demonstrates:

- Best practices for implementing BYOVA gRPC interfaces
- Modular architecture that can be adapted for different use cases
- Well-documented code that serves as a learning resource
- Extensible connector system for various voice agent services

## 📞 Support

For questions about BYOVA integration:
- Check the troubleshooting section in the setup guide
- Review the gateway logs and monitoring interface
- Consult the AWS Lex, CX Agent Studio, and Webex Contact Center documentation
- Reach out to the developer community for assistance

---

**Ready to get started?** Choose the [AWS Lex guide](https://developer.webex.com/webex-contact-center/docs/byova-and-aws-lex) or the [GECX guide](guides/byova-gecx-setup.md).
