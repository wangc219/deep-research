#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>
#import <Vision/Vision.h>

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        if (argc < 2) return 2;
        NSString *path = [NSString stringWithUTF8String:argv[1]];
        __block NSArray<VNRecognizedTextObservation *> *observations = nil;
        __block NSError *requestError = nil;
        VNRecognizeTextRequest *request = [[VNRecognizeTextRequest alloc] initWithCompletionHandler:^(VNRequest *req, NSError *err) {
            observations = (NSArray<VNRecognizedTextObservation *> *)req.results;
            requestError = err;
        }];
        request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
        request.usesLanguageCorrection = YES;

        NSError *error = nil;
        NSURL *url = [NSURL fileURLWithPath:path];
        VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithURL:url options:@{}];
        BOOL ok = [handler performRequests:@[request] error:&error];
        if (!ok || requestError) {
            NSError *reported = error ?: requestError;
            fprintf(stderr, "domain=%s code=%ld description=%s\n",
                    reported.domain.UTF8String, (long)reported.code,
                    reported.localizedDescription.UTF8String);
            return 5;
        }
        NSArray<VNRecognizedTextObservation *> *finalResults = observations ?: (NSArray<VNRecognizedTextObservation *> *)request.results ?: @[];
        fprintf(stderr, "results=%lu\n", (unsigned long)finalResults.count);
        for (VNRecognizedTextObservation *observation in finalResults) {
            VNRecognizedText *candidate = [[observation topCandidates:1] firstObject];
            if (!candidate) continue;
            CGRect b = observation.boundingBox;
            printf("%.5f\t%.5f\t%.5f\t%.5f\t%s\n",
                   b.origin.x, b.origin.y, b.size.width, b.size.height,
                   candidate.string.UTF8String);
        }
    }
    return 0;
}
