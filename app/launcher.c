/* VoiceInput.app の本体。run.sh を子プロセスとして起動して待つだけ。
 *
 * マイク・アクセシビリティ・入力監視の許可を「VoiceInput」という1つのアプリに持たせるためにある。
 * 許可はこのアプリに付き、子プロセス（bash → uv → python）に引き継がれる。
 * Python 側を直しても、このアプリを作り直さない限り許可は残る。
 */
#include <errno.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>

extern char **environ;
static pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

#ifndef RUN_SH
#error "build_app.sh が -DRUN_SH=\"...\" で run.sh の絶対パスを渡す"
#endif

int main(void) {
    /* run.sh の場所は build_app.sh がビルド時に埋め込む（フォルダをどこに置いても動く） */
    char *argv[] = {"/bin/bash", RUN_SH, NULL};
    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    if (posix_spawn(&child, "/bin/bash", NULL, NULL, argv, environ) != 0) return 1;
    int status = 0;
    while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
